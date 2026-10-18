"""Bounded local response reuse and optional background reader preparation.

No FAQ or example questions are loaded. Each inference still receives every
published article. Cache entries contain only validated server-rendered answers;
authentication and fresh publication checks stay in the API/service boundary.
"""

import hashlib
import json
import logging
from collections import OrderedDict
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from copy import deepcopy
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic

import httpx

from app.domain.knowledge.jana_errors import JanaBusy, JanaUnavailable
from app.domain.knowledge.jana_evidence import prepare_evidence, select_excerpts
from app.domain.knowledge.jana_intent import Decision
from app.infrastructure.ai import jana_reader
from app.infrastructure.ai.jana_reader import (
    LocalReader,
    remaining_budget,
    unavailable_evidence,
)

logger = logging.getLogger(__name__)
WARMUP_QUESTION = "Служебная проверка готовности чтения опубликованной базы знаний."


def snapshot_identity(articles: list[dict]) -> str:
    """Include content AND all publication/source metadata, with stable ordering."""
    payload = sorted(articles, key=lambda article: str(article["id"]))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


class ResponseCache:
    """TTL/LRU cache with bounded per-key request coalescing and copy isolation."""

    def __init__(self, clock=monotonic):
        self._clock = clock
        self._lock = Lock()
        self._entries = OrderedDict()
        self._pending: dict[tuple, Future] = {}

    def get_or_compute(
        self, key, compute, *, ttl: float, max_entries: int, wait_seconds: float
    ) -> dict:
        if ttl <= 0:
            return compute()
        with self._lock:
            now = self._clock()
            for expired in [
                k for k, (deadline, _) in self._entries.items() if deadline <= now
            ]:
                del self._entries[expired]
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return deepcopy(cached[1])
            future = self._pending.get(key)
            owner = future is None
            if owner:
                if len(self._pending) >= max_entries:
                    raise JanaBusy("Local reader request queue is full")
                future = Future()
                self._pending[key] = future
        if not owner:
            try:
                return deepcopy(future.result(timeout=remaining_budget(wait_seconds)))
            except FutureTimeout as exc:
                raise JanaBusy("Local reader is busy") from exc
        try:
            result = deepcopy(compute())
            with self._lock:
                # This fallback also represents invalid/schema-rejected model
                # decisions. Never preserve it as a successful model answer.
                if result != unavailable_evidence():
                    self._entries[key] = (self._clock() + ttl, deepcopy(result))
                    self._entries.move_to_end(key)
                    while len(self._entries) > max_entries:
                        self._entries.popitem(last=False)
                future.set_result(result)
            return deepcopy(result)
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)


@dataclass(frozen=True)
class ReaderObservation:
    identity: str
    task_id: int | None
    empty: bool | None


def probe_reader(reader: LocalReader) -> ReaderObservation:
    """Probe only local reader metadata, never execute a model or log prompts.

    llama.cpp has no boot UUID. A failed/recovered health probe, changed model
    properties, decreasing task counter or newly empty slot invalidates observed
    preparation. A restart between polls with identical metadata is not a strong
    boot identity; readiness is a best-effort runtime signal, not a quality claim.
    """
    try:
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
            health = client.get(reader.url + "/health")
            health.raise_for_status()
            response = client.get(reader.url + "/props")
            response.raise_for_status()
            props = response.json()
            n_ctx = props["default_generation_settings"]["n_ctx"]
            if type(n_ctx) is not int or n_ctx <= 0:
                raise ValueError("Invalid context metadata")
            identity = {
                key: props.get(key)
                for key in (
                    "model_alias",
                    "model_path",
                    "model_ftype",
                    "chat_template",
                    "build_info",
                )
            }
            identity.update(url=reader.url, model=reader.model, n_ctx=n_ctx)
            slots_response = client.get(reader.url + "/slots")
            task_id, empty = None, None
            if slots_response.status_code not in {404, 501}:
                slots_response.raise_for_status()
                slots = slots_response.json()
                if (
                    not isinstance(slots, list)
                    or not slots
                    or not all(isinstance(s, dict) for s in slots)
                ):
                    raise ValueError("Invalid slot metadata")
                counters = [s.get("id_task") for s in slots]
                if all(type(value) is int for value in counters):
                    task_id = max(counters)
                if all(
                    type(s.get("n_prompt_tokens")) is int
                    and type(s.get("is_processing")) is bool
                    for s in slots
                ):
                    empty = all(
                        not s["is_processing"] and s["n_prompt_tokens"] == 0
                        for s in slots
                    )
        return ReaderObservation(
            hashlib.sha256(
                json.dumps(identity, sort_keys=True, default=str).encode()
            ).hexdigest(),
            task_id,
            empty,
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise JanaUnavailable("Local reader readiness is unavailable") from exc


def _articles() -> list[dict]:
    # Keep the existing, single publication boundary; avoid an import cycle.
    from app.infrastructure.ai.local_jana import _published_articles

    return _published_articles()


def warm_reader(reader: LocalReader, articles: list[dict]) -> None:
    bundle = prepare_evidence(articles)
    if not bundle.spans:
        raise JanaUnavailable("No published evidence to prepare")
    if not jana_reader._INFERENCE.acquire_background():
        raise JanaBusy("Local reader is busy")
    try:
        decision = reader.select(
            WARMUP_QUESTION, json.loads(bundle.prompt_text)["articles"]
        )
        # Reject invalid shape/coherence and invented evidence exactly as on ask.
        decision = Decision.model_validate(decision.model_dump())
        if decision.evidence_ids:
            select_excerpts(bundle, decision.evidence_ids)
        # Deliberately discard the service decision; no cache or user answer.
    finally:
        jana_reader._INFERENCE.release()


class ReaderRuntime:
    def __init__(
        self,
        *,
        articles=_articles,
        reader_factory=LocalReader,
        probe=probe_reader,
        warm=warm_reader,
    ):
        self._articles, self._reader_factory = articles, reader_factory
        self._probe, self._warm = probe, warm
        self._lock = Lock()
        self._probe_lock = Lock()
        self._settings = None
        self._state = "disabled"
        self._enabled = False
        self._last_snapshot = None
        self._ready_key = None
        self._observation = None
        self._healthy = False
        self._generation = 0
        self._thread = None
        self._stop = Event()
        self._wake = Event()

    def start(self, settings) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._settings = settings
            self._enabled = bool(settings.jana_warmup_enabled)
            self._state = "warming" if self._enabled else "disabled"
            self._ready_key = None
            if not self._enabled:
                return
            self._stop, self._wake = Event(), Event()
            self._thread = Thread(
                target=self._run,
                args=(self._stop, self._wake),
                name="jana-warmup",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._wake.set()
            thread = self._thread
            self._enabled, self._state, self._ready_key = False, "disabled", None
        # HTTP inference is bounded separately. Never hold app shutdown for a
        # cold model request; the daemon cannot publish late readiness afterward.
        if thread is not None:
            thread.join(timeout=0.2)

    def _failed_probe(self) -> None:
        with self._lock:
            if self._healthy:
                self._generation += 1
            self._healthy = False
            self._ready_key = None
            if self._enabled:
                self._state = "unavailable"

    def reader_identity(self, reader: LocalReader, *, wake=True) -> tuple[str, int]:
        # Serialize the short probes AND observation updates. Otherwise two
        # concurrent responses can arrive out of order and mimic a task reset.
        # This lock is never held during model inference.
        with self._probe_lock:
            try:
                observation = self._probe(reader)
            except Exception:
                self._failed_probe()
                raise
            with self._lock:
                previous = self._observation
                restarted = (
                    not self._healthy
                    or previous is None
                    or observation.identity != previous.identity
                    or (
                        observation.task_id is not None
                        and previous.task_id is not None
                        and observation.task_id < previous.task_id
                    )
                    or (observation.empty is True and previous.empty is not True)
                )
                if restarted:
                    self._generation += 1
                    self._ready_key = None
                    if self._enabled:
                        self._state = "warming"
                        if wake:
                            self._wake.set()
                self._observation, self._healthy = observation, True
                return observation.identity, self._generation

    def status(self) -> dict:
        with self._lock:
            if not self._enabled:
                return {"state": "disabled", "enabled": False}
        try:
            snapshot = snapshot_identity(self._articles())
        except Exception:
            with self._lock:
                self._ready_key, self._state = None, "unavailable"
            return {"state": "unavailable", "enabled": True}
        with self._lock:
            if snapshot != self._last_snapshot:
                self._last_snapshot = snapshot
                self._ready_key, self._state = None, "warming"
                self._wake.set()
            return {"state": self._state, "enabled": self._enabled}

    def _cycle(self, stop: Event) -> None:
        reader = self._reader_factory(self._settings)
        identity = self.reader_identity(reader, wake=False)
        articles = self._articles()
        snapshot = snapshot_identity(articles)
        key = (snapshot, identity)
        with self._lock:
            self._last_snapshot = snapshot
            if self._ready_key == key:
                return
            if stop.is_set():
                return
            self._state = "warming"
        self._warm(reader, articles)
        if stop.is_set():
            return
        if snapshot_identity(self._articles()) != snapshot:
            raise JanaUnavailable("Knowledge changed during warmup")
        # Recheck health and the reader instance after a potentially long read.
        after_identity = self.reader_identity(reader, wake=False)
        with self._lock:
            if identity != after_identity or self._observation.empty is True:
                raise JanaUnavailable("Reader changed during warmup")
            if not stop.is_set() and self._enabled:
                self._ready_key, self._state = key, "ready"

    def _run(self, stop: Event, wake: Event) -> None:
        failures, delay = 0, 0.0
        while not stop.is_set():
            if delay:
                # New status/cache requests must not defeat failure backoff.
                (stop if failures else wake).wait(delay)
                wake.clear()
            if stop.is_set():
                break
            try:
                self._cycle(stop)
                failures = 0
                delay = self._settings.jana_warmup_poll_seconds
            except Exception as exc:
                # Never include DB URLs, model outputs or exception text.
                logger.warning("Jana preparation failed: %s", type(exc).__name__)
                with self._lock:
                    if not stop.is_set() and self._enabled:
                        self._ready_key, self._state = None, "unavailable"
                failures = min(failures + 1, 5)
                delay = min(5 * 2 ** (failures - 1), 60)


response_cache = ResponseCache()
reader_runtime = ReaderRuntime()
