"""Reader transport and evidence safety; these tests do not score model semantics."""

import copy
import json

import httpx
import pytest

from app.core.config import Settings
from app.services import jana_reader
from app.services.jana_errors import JanaUnavailable
from app.services.jana_evidence import prepare_evidence
from app.services.jana_intent import Decision, framing_for
from app.services.jana_reader import InvalidDecision, LocalReader, answer_from_knowledge


def article(number=1, content="Получение оборудования доступно через портал. Требуется согласование администратора."):
    return {
        "id": f"50000000-0000-4000-8000-{number:012d}", "title": "Выдача оборудования",
        "source_title": "Инструкция по оборудованию", "content": content, "active": True,
    }


def decision(kind="answer", ids=(), clarification="none"):
    return Decision(understanding="Пользователь запрашивает сведения.", kind=kind,
                    evidence_ids=list(ids), clarification=clarification)


class PlannedReader:
    """Return prescribed selections to isolate validation from language quality."""

    def __init__(self, selected):
        self.selected = selected
        self.calls = []

    def select(self, question, context):
        self.calls.append(("select", question, context))
        if isinstance(self.selected, Exception):
            raise self.selected
        return self.selected

def test_new_active_article_reaches_the_reader_without_faq_registration():
    rows = [article(1), article(2, "Срок возврата оборудования указан в карточке выдачи.")]
    bundle = prepare_evidence(rows)
    chosen = decision(ids=[bundle.documents[1].spans[0].id])
    reader = PlannedReader(chosen)
    result = answer_from_knowledge("Где найти срок возврата оборудования?", rows, reader)
    assert [call[0] for call in reader.calls] == ["select"]
    expected_context = json.loads(bundle.prompt_text)["articles"]
    assert reader.calls[0][2] == expected_context
    assert {doc["article_id"] for doc in expected_context} == {row["id"] for row in rows}
    assert result["sources"][0]["id"] == rows[1]["id"]
    assert result["sources"][0]["excerpt"] == rows[1]["content"]
    assert result["grounded"] is True and result["mode"] == "excerpts"


def test_edit_outside_selected_sentence_invalidates_decision_without_retry():
    row = article()
    old_id = prepare_evidence([row]).spans[0].id
    updated = {**row, "content": row["content"] + " Выдача временно приостановлена."}
    reader = PlannedReader(decision(ids=[old_id]))
    result = answer_from_knowledge("Как получить оборудование?", [updated], reader)
    assert [call[0] for call in reader.calls] == ["select"]
    assert result == jana_reader.unavailable_evidence()


def test_unknown_id_is_not_repaired_or_silently_replaced():
    row = article()
    reader = PlannedReader(decision(ids=["InventedSentence"]))
    result = answer_from_knowledge("Как получить оборудование?", [row], reader)
    assert len(reader.calls) == 1
    assert result["sources"] == [] and result["grounded"] is False


def test_deactivated_only_source_is_not_sent_to_model():
    reader = PlannedReader(decision("unknown"))
    result = answer_from_knowledge("Как получить оборудование?", [{**article(), "active": False}], reader)
    assert reader.calls == []
    assert result == jana_reader.unavailable_evidence()


def test_quotes_preserve_internal_context_and_source_boundaries():
    a = article(1, "Обычно можно получить устройство. Но только после согласования. Затем заберите его.")
    b = article(2, "Выдача происходит на складе.")
    bundle = prepare_evidence([a, b])
    ids = [bundle.documents[1].spans[0].id,
           bundle.documents[0].spans[0].id, bundle.documents[0].spans[-1].id]
    result = answer_from_knowledge("Вопрос о выдаче", [a, b], PlannedReader(decision(ids=ids)))
    assert result["sources"] == [
        {"id": b["id"], "title": b["source_title"],
         "url": f"/api/v1/ai/sources/{b['id']}", "excerpt": b["content"]},
        {"id": a["id"], "title": a["source_title"],
         "url": f"/api/v1/ai/sources/{a['id']}", "excerpt": a["content"]},
    ]
    assert result["answer"].strip() == f"{b['content']} [1]\n\n{a['content']} [2]"
    assert result["answer"].count("Но только после согласования.") == 1
    assert "http" not in result["answer"]


def test_clarification_requests_context_without_hr_escalation_or_citations():
    selection = decision("clarify", clarification="object")
    reader = PlannedReader(selection)
    result = answer_from_knowledge("Как это сделать?", [article()], reader)
    assert [call[0] for call in reader.calls] == ["select"]
    assert result == {
        "answer": framing_for(selection), "sources": [], "grounded": False,
        "escalation_suggested": False, "mode": "refusal",
    }


def test_unknown_decision_has_no_evidence_or_grounded_claim():
    row = article()
    reader = PlannedReader(decision("unknown"))
    result = answer_from_knowledge("Какой срок указан?", [row], reader)
    assert result == {
        "answer": framing_for(decision("unknown")), "sources": [], "grounded": False,
        "escalation_suggested": True, "mode": "refusal",
    }


@pytest.mark.parametrize("kind", ["action", "personal", "injection"])
def test_boundary_modes_only_frame_evidence_and_do_not_modify_input_or_execute_actions(kind):
    rows = [article()]
    original = copy.deepcopy(rows)
    chosen = decision(kind, [prepare_evidence(rows).spans[0].id])
    reader = PlannedReader(chosen)
    result = answer_from_knowledge("Запрос пользователя", rows, reader)
    assert rows == original
    assert [call[0] for call in reader.calls] == ["select"]
    assert result["answer"].startswith(framing_for(chosen) + "\n\n")
    assert result["sources"][0]["excerpt"] in rows[0]["content"]
    assert result["escalation_suggested"] is True


def test_partial_answer_keeps_an_explicit_limit_and_selected_quotes():
    rows = [article()]
    chosen = decision("partial", [prepare_evidence(rows).spans[0].id])
    result = answer_from_knowledge("Составной вопрос", rows, PlannedReader(chosen))
    assert result["answer"].startswith(framing_for(chosen))
    assert result["grounded"] is True and result["escalation_suggested"] is True


@pytest.mark.parametrize("kind", ["action", "personal", "injection"])
def test_boundary_routes_without_evidence_keep_their_limitations(kind):
    rows = [article()]
    selected = decision(kind)
    reader = PlannedReader(selected)
    result = answer_from_knowledge("Запрос пользователя", rows, reader)
    assert result["answer"] == framing_for(selected)
    assert result["escalation_suggested"] is True
    assert result["sources"] == [] and result["grounded"] is False


def test_model_written_intent_summary_is_never_rendered_as_fact_or_source():
    rows = [article()]
    span = prepare_evidence(rows).spans[0]
    selected = Decision(
        understanding="UNTRUSTED MODEL SUMMARY https://outside.invalid/ made-up claim",
        kind="answer", evidence_ids=[span.id], clarification="none",
    )
    result = answer_from_knowledge("Вопрос о выдаче", rows, PlannedReader(selected))
    assert selected.understanding not in json.dumps(result, ensure_ascii=False)
    assert result["answer"] == f"{span.text} [1]"


def test_malformed_decision_fails_closed():
    reader = PlannedReader(InvalidDecision("Malformed output"))
    assert answer_from_knowledge("Вопрос", [article()], reader) == jana_reader.unavailable_evidence()


def test_transport_failure_is_reported_as_unavailable_and_releases_inference_slot():
    with pytest.raises(JanaUnavailable):
        answer_from_knowledge("Вопрос", [article()], PlannedReader(JanaUnavailable("Server stopped")))
    # A transport outage must not permanently hold the single inference slot.
    result = answer_from_knowledge("Вопрос", [article()], PlannedReader(decision("unknown")))
    assert result["answer"] == framing_for(decision("unknown"))


def test_busy_reader_fails_explicitly_without_calling_model(monkeypatch):
    class Busy:
        def acquire(self, timeout):
            return False

        def release(self):
            raise AssertionError("An unacquired slot must not be released")

    monkeypatch.setattr(jana_reader, "_INFERENCE", Busy())
    reader = PlannedReader(decision("unknown"))
    with pytest.raises(JanaUnavailable, match="busy"):
        answer_from_knowledge("Вопрос", [article()], reader)
    assert reader.calls == []


@pytest.fixture
def mock_server(monkeypatch):
    real_client = httpx.Client
    real_check_context = LocalReader._check_context
    captured = {"client_options": [], "requests": []}

    def configure(handler, *, preflight=False):
        def transport(request):
            captured["requests"].append(request)
            return handler(request)

        def client(**kwargs):
            captured["client_options"].append(kwargs)
            return real_client(**kwargs, transport=httpx.MockTransport(transport))

        monkeypatch.setattr(jana_reader.httpx, "Client", client)
        monkeypatch.setattr(LocalReader, "_check_context", real_check_context if preflight else lambda *_: None)
        return captured

    return configure


def local_reader(url="http://127.0.0.1:8081"):
    return LocalReader(Settings(_env_file=None, jana_reader_url=url))


def response(content, finish="stop"):
    return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": {"content": content}}]})


def test_local_transport_disables_proxies_and_redirects_and_constrains_model_output(mock_server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://external-proxy.invalid:9000")
    captured = mock_server(lambda request: response(decision("unknown").model_dump_json()))
    result = local_reader().select("Вопрос", [{
        "article_id": "a1", "sentences": [{"id": "Scurrent", "text": "Текущий источник."}],
    }])
    assert result.kind == "unknown"
    options = captured["client_options"][0]
    assert options["trust_env"] is False and options["follow_redirects"] is False
    assert str(captured["requests"][0].url) == "http://127.0.0.1:8081/v1/chat/completions"
    payload = json.loads(captured["requests"][0].content)
    assert payload["stream"] is False
    assert payload["cache_prompt"] is True
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert payload["response_format"]["json_schema"]["schema"]["properties"]["evidence_ids"]["items"]["enum"] == ["Scurrent"]
    assert payload["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8081", "http://localhost:8081", "http://example.com", "http://192.168.1.3:8081",
    "http://127.0.0.1.example.com", "http://user:password@127.0.0.1:8081",
    "http://127.0.0.1:8081/private", "http://127.0.0.1:8081?send=1",
    "http://127.0.0.1:8081#fragment", "http://127.0.0.1:abc", "http://127.0.0.1:99999",
])
def test_only_valid_loopback_server_addresses_are_accepted(url):
    with pytest.raises(JanaUnavailable):
        local_reader(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8081", "http://[::1]:8081/"])
def test_explicit_loopback_addresses_are_accepted(url):
    assert local_reader(url).url == url.rstrip("/")


@pytest.mark.parametrize("content", [
    "not-json", "[]", "{}", "null",
    '{"kind":"answer","evidence_ids":[],"clarification":"none"}',
    '{"kind":"unknown","evidence_ids":[],"clarification":"none","answer":"Invented"}',
])
def test_malformed_model_content_is_not_an_answer(mock_server, content):
    mock_server(lambda request: response(content))
    with pytest.raises(InvalidDecision):
        local_reader().select("Вопрос", [])


@pytest.mark.parametrize("finish", ["length", "tool_calls", "content_filter", None])
def test_unfinished_or_non_text_completion_is_not_accepted(mock_server, finish):
    mock_server(lambda request: response(decision("unknown").model_dump_json(), finish))
    with pytest.raises(InvalidDecision):
        local_reader().select("Вопрос", [])


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}, {"choices": [None]}])
def test_malformed_server_response_is_not_accepted(mock_server, body):
    mock_server(lambda request: httpx.Response(200, json=body))
    with pytest.raises(InvalidDecision):
        local_reader().select("Вопрос", [])


def test_http_503_does_not_become_an_unknown_fact_answer(mock_server):
    mock_server(lambda request: httpx.Response(503, json={"error": "busy"}))
    with pytest.raises(JanaUnavailable):
        local_reader().select("Вопрос", [])


def test_http_redirect_to_cloud_is_not_followed(mock_server):
    captured = mock_server(lambda request: httpx.Response(307, headers={"location": "https://outside.invalid/"}))
    with pytest.raises(JanaUnavailable):
        local_reader().select("Вопрос", [])
    assert len(captured["requests"]) == 1


def test_timeout_does_not_fall_back_to_cloud_or_uncited_text(mock_server):
    def timeout(request):
        raise httpx.ReadTimeout("Timed out", request=request)

    captured = mock_server(timeout)
    with pytest.raises(JanaUnavailable):
        local_reader().select("Вопрос", [])
    assert len(captured["requests"]) == 1


def preflight_server(*, token_count=100, context_size=1024, failures=None):
    """Fake only server responses; exercise the real context-budget code."""
    failures = failures or {}

    def handler(request):
        path = request.url.path
        if path in failures:
            return failures[path]
        if path == "/props":
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": context_size}})
        if path == "/apply-template":
            return httpx.Response(200, json={"prompt": "Exact rendered chat template."})
        if path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(token_count))})
        if path == "/v1/chat/completions":
            return response(decision("unknown").model_dump_json())
        raise AssertionError(f"Unexpected endpoint: {path}")

    return handler


def test_preflight_counts_the_complete_server_chat_template_before_inference(mock_server):
    captured = mock_server(preflight_server(), preflight=True)
    context = [{"article_id": "new", "sentences": [{"id": "s1", "text": "Полная статья."}]}]
    assert local_reader().select("Вопрос?", context).kind == "unknown"
    requests = captured["requests"]
    assert [request.url.path for request in requests] == [
        "/props", "/apply-template", "/tokenize", "/v1/chat/completions",
    ]
    template_payload = json.loads(requests[1].content)
    inference_payload = json.loads(requests[3].content)
    assert template_payload["messages"] == inference_payload["messages"]
    assert template_payload["chat_template_kwargs"] == inference_payload["chat_template_kwargs"]
    assert json.loads(template_payload["messages"][1]["content"])["articles"] == context
    assert json.loads(requests[2].content) == {
        "content": "Exact rendered chat template.", "add_special": True,
    }


def test_preflight_reserves_output_and_safety_tokens_at_the_exact_boundary(mock_server):
    # 480 input + 512 output + 32 safety tokens exactly fills this context.
    captured = mock_server(preflight_server(token_count=480, context_size=1024), preflight=True)
    assert local_reader().select("Вопрос", []).kind == "unknown"
    assert captured["requests"][-1].url.path == "/v1/chat/completions"


def test_context_overflow_never_calls_inference_or_truncates_sources(mock_server):
    captured = mock_server(preflight_server(token_count=481, context_size=1024), preflight=True)
    with pytest.raises(JanaUnavailable, match="context"):
        local_reader().select("Вопрос", [])
    assert [request.url.path for request in captured["requests"]] == [
        "/props", "/apply-template", "/tokenize",
    ]


@pytest.mark.parametrize("endpoint", ["/props", "/apply-template", "/tokenize"])
def test_preflight_http_error_stops_before_inference(mock_server, endpoint):
    captured = mock_server(preflight_server(failures={endpoint: httpx.Response(503)}), preflight=True)
    with pytest.raises(JanaUnavailable):
        local_reader().select("Вопрос", [])
    assert captured["requests"][-1].url.path == endpoint
    assert all(request.url.path != "/v1/chat/completions" for request in captured["requests"])


@pytest.mark.parametrize("context_size", ["1024", None, 0, -1, True])
def test_invalid_context_size_is_not_used_as_an_inference_budget(mock_server, context_size):
    captured = mock_server(preflight_server(context_size=context_size), preflight=True)
    with pytest.raises(InvalidDecision):
        local_reader().select("Вопрос", [])
    assert all(request.url.path != "/v1/chat/completions" for request in captured["requests"])


@pytest.mark.parametrize("tokens", ["123", {"0": 42}, None, ["42"], [True], [1.5]])
def test_malformed_tokenizer_payload_cannot_undercount_context(mock_server, tokens):
    captured = mock_server(preflight_server(failures={
        "/tokenize": httpx.Response(200, json={"tokens": tokens}),
    }), preflight=True)
    with pytest.raises(InvalidDecision):
        local_reader().select("Вопрос", [])
    assert captured["requests"][-1].url.path == "/tokenize"
    assert all(request.url.path != "/v1/chat/completions" for request in captured["requests"])


@pytest.mark.parametrize("prompt", [None, ["text"], {"text": "prompt"}, 42])
def test_malformed_template_is_not_forwarded_to_tokenizer_or_inference(mock_server, prompt):
    captured = mock_server(preflight_server(failures={
        "/apply-template": httpx.Response(200, json={"prompt": prompt}),
    }), preflight=True)
    with pytest.raises(InvalidDecision):
        local_reader().select("Вопрос", [])
    assert captured["requests"][-1].url.path == "/apply-template"
