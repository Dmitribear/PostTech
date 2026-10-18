"""Offline runtime/cache contracts; these are not model-accuracy evaluations."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.presentation.http.security import get_current_user
from app.main import app
from app.domain.models import UserContext
from app.infrastructure.ai import local_jana as jana, jana_runtime as runtime_module
from app.domain.knowledge.jana_errors import JanaBusy, JanaUnavailable
from app.domain.knowledge.jana_intent import Decision
from app.domain.knowledge.publication import snapshot_version, usable
from app.infrastructure.ai.jana_reader import unavailable_evidence
from app.infrastructure.ai.jana_runtime import (
    ReaderObservation, ReaderRuntime, ResponseCache, WARMUP_QUESTION,
    probe_reader, snapshot_identity, warm_reader,
)

NOW = datetime.now(timezone.utc)
ARTICLE = dict(id=str(UUID(int=9001)), title="Отпуск", source_title="Правила отпуска",
               content="Окончательное решение принимает HR. Дни списываются один раз.",
               source_url=None, active=True, editorial_state="published", version="1",
               updated_at=NOW.isoformat(), reviewed_at=(NOW-timedelta(days=1)).isoformat(),
               review_due_at=(NOW+timedelta(days=30)).isoformat())
ANSWER = dict(answer="Цитата [1]", sources=[dict(id=ARTICLE["id"], title="Правила",
              url="/api/v1/ai/sources/"+ARTICLE["id"], excerpt="Цитата")],
              grounded=True, escalation_suggested=False, mode="excerpts")


def cached(cache, key, compute, ttl=300, max_entries=64, wait_seconds=1):
    return cache.get_or_compute(key, compute, ttl=ttl, max_entries=max_entries,
                                wait_seconds=wait_seconds)


def test_response_cache_copy_isolation_ttl_and_lru():
    now = [0.0]
    cache = ResponseCache(clock=lambda: now[0])
    calls = []
    def compute():
        calls.append(1)
        return ANSWER
    first = cached(cache, ("one",), compute, ttl=10, max_entries=2)
    first["sources"][0]["url"] += "?changed=true"
    assert cached(cache, ("one",), compute)["sources"][0]["url"] == ANSWER["sources"][0]["url"]
    assert len(calls) == 1
    cached(cache, ("two",), compute, max_entries=2)
    cached(cache, ("one",), compute, max_entries=2)
    cached(cache, ("three",), compute, max_entries=2)
    cached(cache, ("two",), compute, max_entries=2)
    assert len(calls) == 4  # the least recently used entry was evicted
    now[0] = 301
    cached(cache, ("two",), compute, max_entries=2)
    assert len(calls) == 5
    assert ANSWER["sources"][0]["url"].endswith(ARTICLE["id"])


def test_cache_disabled_is_unconditional_compute():
    cache, calls = ResponseCache(), []
    for _ in range(2):
        cached(cache, ("one",), lambda: calls.append(1) or ANSWER, ttl=0)
    assert calls == [1, 1]


@pytest.mark.parametrize("failure", [True, False])
def test_errors_and_invalid_decision_fallback_are_not_cached(failure):
    calls, cache = [], ResponseCache()
    def compute():
        calls.append(1)
        if failure:
            raise JanaUnavailable("private detail")
        return unavailable_evidence()
    for _ in range(2):
        if failure:
            with pytest.raises(JanaUnavailable):
                cached(cache, ("one",), compute)
        else:
            assert cached(cache, ("one",), compute) == unavailable_evidence()
    assert len(calls) == 2 and not cache._pending


def test_same_question_concurrent_calls_share_only_one_computation():
    cache, entered, release, calls = ResponseCache(), Event(), Event(), []
    def compute():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return ANSWER
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(cached, cache, ("one",), compute) for _ in range(4)]
        assert entered.wait(1)
        release.set()
        results = [future.result(timeout=2) for future in futures]
    assert len(calls) == 1
    results[0]["sources"].clear()
    assert len(results[1]["sources"]) == 1


def test_pending_requests_are_bounded_and_waiter_timeout_does_not_cancel_owner():
    cache, entered, release = ResponseCache(), Event(), Event()
    def compute():
        entered.set()
        assert release.wait(2)
        return ANSWER
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(cached, cache, ("one",), compute, 300, 1)
        assert entered.wait(1)
        with pytest.raises(JanaBusy, match="queue is full"):
            cached(cache, ("two",), lambda: ANSWER, max_entries=1)
        with pytest.raises(JanaBusy, match="busy"):
            cached(cache, ("one",), lambda: ANSWER, max_entries=1, wait_seconds=0.01)
        release.set()
        assert owner.result(timeout=2) == ANSWER
    assert cached(cache, ("one",), lambda: pytest.fail("must use cache")) == ANSWER


class Reader:
    url, model, timeout = "http://127.0.0.1:8081", "local", 5
    def __init__(self):
        self.calls = []
    def select(self, question, context):
        self.calls.append((question, deepcopy(context)))
        return Decision(understanding=question, kind="answer", clarification="none",
                        evidence_ids=[context[0]["sentences"][0]["id"]])


@pytest.fixture
def service(monkeypatch):
    state = {"rows": [deepcopy(ARTICLE)], "identity": ("local", 1), "reads": 0}
    reader = Reader()
    def published():
        state["reads"] += 1
        return deepcopy([row for row in state["rows"] if usable(row)])
    settings = Settings(_env_file=None, jana_response_cache_ttl_seconds=300)
    monkeypatch.setattr(jana, "get_settings", lambda: settings)
    monkeypatch.setattr(jana, "_published_articles", published)
    monkeypatch.setattr(jana, "LocalReader", lambda _: reader)
    monkeypatch.setattr(jana, "response_cache", ResponseCache())
    monkeypatch.setattr(jana.reader_runtime, "reader_identity", lambda _: state["identity"])
    return state, reader


def test_answer_reuse_keeps_fresh_metadata_language_and_two_db_checks(service):
    state, reader = service
    ru = jana.answer_question("Кто одобряет отпуск?")
    reads = state["reads"]
    kk = jana.answer_question("Кто одобряет отпуск?", language="kk")
    assert state["reads"] == reads+2  # cache does not bypass publication checks
    again = jana.answer_question("Кто одобряет отпуск?")
    assert len(reader.calls) == 1 and ru == again
    assert "орыс тілі" in kk["answer"] and "орыс тілі" not in again["answer"]
    assert ru["sources"][0]["url"].count("?version=") == 1
    assert ru["sources"][0]["version"] == snapshot_version(ARTICLE)


@pytest.mark.parametrize("field,value", [
    ("content", "Отпуск подтверждает директор."), ("title", "Новая статья"),
    ("source_title", "Новый документ"), ("source_url", "https://example.org/policy"),
    ("version", "2"), ("updated_at", (NOW+timedelta(seconds=1)).isoformat()),
    ("reviewed_at", (NOW-timedelta(hours=1)).isoformat()),
    ("review_due_at", (NOW+timedelta(days=20)).isoformat()),
])
def test_any_published_snapshot_change_invalidates_answer(service, field, value):
    state, reader = service
    jana.answer_question("Кто одобряет отпуск?")
    state["rows"][0][field] = value
    result = jana.answer_question("Кто одобряет отпуск?")
    assert len(reader.calls) == 2
    assert result["sources"][0]["version"] == snapshot_version(state["rows"][0])


@pytest.mark.parametrize("change", [
    {"active": False}, {"editorial_state": "draft"},
    {"review_due_at": (NOW-timedelta(hours=1)).isoformat()},
])
def test_unpublished_or_expired_knowledge_is_never_served_from_cache(service, change):
    state, reader = service
    jana.answer_question("Кто одобряет отпуск?")
    state["rows"][0].update(change)
    answer = jana.answer_question("Кто одобряет отпуск?")
    assert not answer["sources"] and not answer["grounded"]
    assert len(reader.calls) == 1


def test_new_article_exact_question_and_reader_identity_all_invalidate(service):
    state, reader = service
    jana.answer_question("Кто одобряет отпуск?")
    jana.answer_question("кто одобряет отпуск?")
    assert len(reader.calls) == 2  # no fuzzy or FAQ lookup
    state["rows"].append(ARTICLE | {"id": str(UUID(int=9002)), "content": "Дополнительное правило."})
    jana.answer_question("Кто одобряет отпуск?")
    assert len(reader.calls) == 3 and len(reader.calls[-1][1]) == 2
    state["identity"] = ("local", 2)
    jana.answer_question("Кто одобряет отпуск?")
    assert len(reader.calls) == 4


def test_change_during_cache_hit_is_rejected(service, monkeypatch):
    jana.answer_question("Кто одобряет отпуск?")
    snapshots = iter([[ARTICLE], [ARTICLE | {"content": "Изменено."}]])
    monkeypatch.setattr(jana, "_published_articles", lambda: next(snapshots))
    with pytest.raises(JanaUnavailable, match="Knowledge changed"):
        jana.answer_question("Кто одобряет отпуск?")


def test_change_during_miss_never_enters_response_cache(service, monkeypatch):
    state, reader = service
    original = jana._published_articles
    snapshots = iter([[ARTICLE], [ARTICLE | {"content": "Изменено."}]])
    monkeypatch.setattr(jana, "_published_articles", lambda: next(snapshots))
    with pytest.raises(JanaUnavailable, match="Knowledge changed"):
        jana.answer_question("Кто одобряет отпуск?")
    monkeypatch.setattr(jana, "_published_articles", original)
    jana.answer_question("Кто одобряет отпуск?")
    assert len(reader.calls) == 2


def configured_runtime(**overrides):
    rows = [deepcopy(ARTICLE)]
    state = {"observation": ReaderObservation("local", 10, False), "warms": 0, "fail": False}
    def probe(_):
        if state["fail"]:
            raise JanaUnavailable("private probe detail")
        return state["observation"]
    def warm(_, articles):
        assert articles == rows
        state["warms"] += 1
    kwargs = dict(articles=lambda: deepcopy(rows), reader_factory=lambda _: Reader(), probe=probe, warm=warm)
    kwargs.update(overrides)
    runtime = ReaderRuntime(**kwargs)
    runtime._settings = SimpleNamespace(jana_warmup_enabled=True, jana_warmup_poll_seconds=5)
    runtime._enabled, runtime._state = True, "warming"
    return runtime, rows, state


def test_runtime_requires_validated_warmup_not_just_health():
    runtime, _, state = configured_runtime()
    assert runtime.status() == {"state": "warming", "enabled": True}
    runtime.reader_identity(Reader())
    assert runtime.status()["state"] == "warming"
    runtime._cycle(Event())
    assert runtime.status()["state"] == "ready" and state["warms"] == 1
    runtime._cycle(Event())
    assert state["warms"] == 1  # periodic health checks are not inference


def test_ready_status_immediately_invalidates_on_database_edit():
    runtime, rows, state = configured_runtime()
    runtime._cycle(Event())
    rows[0]["source_title"] = "Обновлённый документ"
    assert runtime.status()["state"] == "warming"
    assert runtime._wake.is_set()
    runtime._cycle(Event())
    assert runtime.status()["state"] == "ready" and state["warms"] == 2


@pytest.mark.parametrize("observation", [ReaderObservation("new-model", 11, False),
                                          ReaderObservation("local", 0, False),
                                          ReaderObservation("local", 10, True)])
def test_model_change_task_reset_and_empty_slot_invalidate_runtime(observation):
    runtime, _, state = configured_runtime()
    runtime._cycle(Event())
    state["observation"] = observation
    old_identity = runtime._ready_key[1]
    assert runtime.reader_identity(Reader()) != old_identity
    assert runtime.status()["state"] == "warming"


def test_task_counter_increase_is_not_cache_invalidation():
    runtime, _, state = configured_runtime()
    first = runtime.reader_identity(Reader())
    state["observation"] = ReaderObservation("local", 11, False)
    assert runtime.reader_identity(Reader()) == first


def test_probe_failure_recovery_requires_new_warmup():
    runtime, _, state = configured_runtime()
    runtime._cycle(Event())
    state["fail"] = True
    with pytest.raises(JanaUnavailable):
        runtime.reader_identity(Reader())
    assert runtime.status()["state"] == "unavailable"
    state["fail"] = False
    runtime._cycle(Event())
    assert runtime.status()["state"] == "ready" and state["warms"] == 2


def test_empty_slot_after_service_decision_cannot_claim_ready():
    runtime, _, state = configured_runtime()
    state["observation"] = ReaderObservation("local", 0, True)
    with pytest.raises(JanaUnavailable, match="Reader changed"):
        runtime._cycle(Event())
    assert runtime.status()["state"] != "ready"


def test_warmup_checks_complete_evidence_and_discards_output():
    reader = Reader()
    second = ARTICLE | {"id": str(UUID(int=9002)), "content": "Второй документ."}
    assert warm_reader(reader, [ARTICLE, second]) is None
    question, context = reader.calls[0]
    assert question == WARMUP_QUESTION and len(context) == 2
    assert "Окончательное решение принимает HR." in [s["text"] for s in context[0]["sentences"]]


def test_warmup_rejects_invented_evidence_and_empty_knowledge():
    class InvalidReader(Reader):
        def select(self, *_):
            return Decision(understanding="Проверка", kind="answer", clarification="none", evidence_ids=["invented"])
    with pytest.raises(ValueError):
        warm_reader(InvalidReader(), [ARTICLE])
    with pytest.raises(JanaUnavailable, match="No published"):
        warm_reader(Reader(), [])
    # Semaphore is released after rejection, so another valid read works.
    assert warm_reader(Reader(), [ARTICLE]) is None


def test_warmup_never_queues_behind_or_in_front_of_users(monkeypatch):
    gate = runtime_module.jana_reader.InferenceAdmission()
    monkeypatch.setattr(runtime_module.jana_reader, "_INFERENCE", gate)
    assert gate.acquire(timeout=0)
    reader = Reader()
    with pytest.raises(JanaBusy):
        warm_reader(reader, [ARTICLE])
    assert not gate._waiting and not reader.calls
    gate.release()
    assert warm_reader(reader, [ARTICLE]) is None


def test_startup_default_disabled_has_no_network_or_database(monkeypatch):
    def forbidden(*_, **__):
        pytest.fail("Default runtime must not access network, KB or model")
    runtime = ReaderRuntime(articles=forbidden, reader_factory=forbidden, probe=forbidden, warm=forbidden)
    settings = Settings(_env_file=None)
    assert not settings.jana_warmup_enabled and settings.jana_response_cache_ttl_seconds == 0
    runtime.start(settings)
    assert runtime.status() == {"state": "disabled", "enabled": False}
    runtime.stop()


def test_background_start_and_shutdown_do_not_wait_for_inference():
    entered, release = Event(), Event()
    def blocked_warm(*_):
        entered.set()
        assert release.wait(3)
    runtime, _, _ = configured_runtime(warm=blocked_warm)
    began = monotonic()
    runtime.start(runtime._settings)
    assert monotonic()-began < 0.5 and entered.wait(1)
    assert runtime.status()["state"] == "warming"
    began = monotonic()
    runtime.stop()
    assert monotonic()-began < 0.5
    release.set()
    runtime._thread.join(1)
    assert not runtime._thread.is_alive()
    assert runtime.status() == {"state": "disabled", "enabled": False}


def test_status_database_failure_exposes_no_details():
    def broken():
        raise RuntimeError("password=private model output")
    runtime, _, _ = configured_runtime(articles=broken)
    assert runtime.status() == {"state": "unavailable", "enabled": True}


def test_failure_retries_are_bounded_even_when_status_wakes_runtime(caplog):
    class Stop:
        stopped = False
        waits = []
        def is_set(self): return self.stopped
        def wait(self, delay): self.waits.append(delay)
    stop, wake = Stop(), Event()
    runtime, _, _ = configured_runtime()
    calls = []
    def fail(_):
        calls.append(1)
        wake.set()  # repeated status polling must not make retries busy-loop
        if len(calls) == 7:
            stop.stopped = True
        raise JanaUnavailable("secret database connection")
    runtime._cycle = fail
    runtime._run(stop, wake)
    assert stop.waits == [5, 10, 20, 40, 60, 60]
    assert "secret database connection" not in caplog.text
    assert "JanaUnavailable" in caplog.text


def test_changed_snapshot_during_warmup_never_becomes_ready():
    runtime, rows, _ = configured_runtime()
    def edit_during_warmup(*_):
        rows[0]["content"] = "Новое правило."
    runtime._warm = edit_during_warmup
    with pytest.raises(JanaUnavailable, match="Knowledge changed"):
        runtime._cycle(Event())
    assert runtime.status()["state"] != "ready"


def test_probes_serialize_observation_updates():
    active, maximum, lock = [0], [0], Lock()
    def probe(_):
        with lock:
            active[0] += 1
            maximum[0] = max(maximum[0], active[0])
        sleep(0.01)
        with lock:
            active[0] -= 1
        return ReaderObservation("local", 1, False)
    runtime = ReaderRuntime(probe=probe)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: runtime.reader_identity(Reader()), range(4)))
    assert maximum[0] == 1 and len(set(results)) == 1


def test_local_metadata_probe_has_no_inference_and_hashes_private_properties(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request.url.path)
        assert request.method == "GET"
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/props":
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 8192},
                                           "model_path": "/private/model.gguf", "chat_template": "private template"})
        return httpx.Response(200, json=[{"id_task": 12, "n_prompt_tokens": 4000, "is_processing": False,
                                         "prompt": "private prompt must never be returned"}])
    client_type = httpx.Client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return client_type(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(runtime_module.httpx, "Client", client)
    observation = probe_reader(Reader())
    assert requests == ["/health", "/props", "/slots"]
    assert observation.task_id == 12 and observation.empty is False
    assert "private" not in repr(observation) and len(observation.identity) == 64


def test_ai_status_requires_authentication_and_has_bounded_shape(monkeypatch):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.pop(get_current_user, None)
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/ai/status").status_code == 401
            app.dependency_overrides[get_current_user] = lambda: UserContext(id="employee", auth_user_id="auth", role="worker")
            result = client.get("/api/v1/ai/status")
            assert result.status_code == 200
            assert result.json() == {"state": "disabled", "enabled": False}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_full_snapshot_identity_is_order_stable_and_metadata_sensitive():
    second = ARTICLE | {"id": str(UUID(int=9002))}
    assert snapshot_identity([ARTICLE, second]) == snapshot_identity([second, ARTICLE])
    assert snapshot_identity([ARTICLE]) != snapshot_identity([ARTICLE | {"source_url": "https://example.org"}])
