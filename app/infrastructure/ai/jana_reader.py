"""Local language understanding with server-owned, verbatim evidence only.

The reader can select source spans and response framing. It cannot author facts,
URLs, SQL, tools, personal values, or execute actions. Every request searches the
complete published knowledge snapshot, independently of historical FAQ examples.
"""

import json
import logging
from threading import BoundedSemaphore
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.domain.knowledge.jana_errors import JanaUnavailable
from app.domain.knowledge.jana_evidence import prepare_evidence, select_excerpts
from app.domain.knowledge.jana_intent import (
    Decision,
    build_intent_messages,
    decision_json_schema,
    framing_for,
)
from app.infrastructure.config import Settings

logger = logging.getLogger(__name__)
_INFERENCE = BoundedSemaphore(1)


class InvalidDecision(ValueError):
    """The local model did not produce a usable, bounded selection."""


class LocalReader:
    def __init__(self, settings: Settings):
        try:
            address = urlsplit(settings.jana_reader_url)
            port = address.port
        except ValueError as exc:
            raise JanaUnavailable("Invalid local reader address") from exc
        # Neither environment proxies nor an accidentally configured cloud URL
        # may receive employee questions or company knowledge.
        if (
            address.scheme != "http"
            or address.hostname not in {"127.0.0.1", "::1"}
            or address.username
            or address.password
            or address.query
            or address.fragment
            or address.path not in {"", "/"}
            or port == 0
        ):
            raise JanaUnavailable("Jana reader must be a loopback HTTP service")
        self.url = settings.jana_reader_url.rstrip("/")
        self.model = settings.jana_reader_model
        self.timeout = settings.jana_reader_timeout_seconds

    def _check_context(self, client: httpx.Client, messages: list[dict]) -> None:
        """Count the server's real chat template tokens; never truncate sources."""
        props = client.get(self.url + "/props")
        props.raise_for_status()
        context_size = props.json()["default_generation_settings"]["n_ctx"]
        templated = client.post(
            self.url + "/apply-template",
            json={
                "messages": messages,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        templated.raise_for_status()
        prompt = templated.json()["prompt"]
        if not isinstance(prompt, str):
            raise InvalidDecision("Invalid model template")
        tokens = client.post(
            self.url + "/tokenize",
            json={
                "content": prompt,
                "add_special": True,
            },
        )
        tokens.raise_for_status()
        token_ids = tokens.json()["tokens"]
        if not isinstance(token_ids, list) or not all(
            type(t) is int for t in token_ids
        ):
            raise InvalidDecision("Invalid model token count")
        count = len(token_ids)
        if type(context_size) is not int or context_size <= 0:
            raise InvalidDecision("Invalid model context size")
        if count + 512 + 32 > context_size:
            raise JanaUnavailable(
                "Whole knowledge base exceeds the local model context"
            )

    def _decide(self, messages: list[dict], *, available_ids=None) -> Decision:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "seed": 42,
            "max_tokens": 512,
            "stream": False,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "evidence_decision",
                    "strict": True,
                    "schema": decision_json_schema(available_ids),
                },
            },
        }
        try:
            with httpx.Client(
                timeout=self.timeout, trust_env=False, follow_redirects=False
            ) as client:
                self._check_context(client, messages)
                response = client.post(self.url + "/v1/chat/completions", json=payload)
                response.raise_for_status()
                raw = response.json()
            choice = raw["choices"][0]
            if choice["finish_reason"] != "stop":
                raise InvalidDecision("Incomplete model decision")
            return Decision.model_validate_json(choice["message"]["content"])
        except httpx.HTTPError as exc:
            logger.warning("Local reader transport failed: %s", type(exc).__name__)
            raise JanaUnavailable("Local reader is unavailable") from exc
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise InvalidDecision("Invalid model decision") from exc

    def select(self, question: str, context) -> Decision:
        # Constrain generated references to this complete snapshot. This avoids
        # rejecting an otherwise useful selection just for a mistyped hash ID.
        available_ids = [
            span["id"] for article in context for span in article["sentences"]
        ]
        return self._decide(
            build_intent_messages(question, context), available_ids=available_ids
        )


def unavailable_evidence() -> dict:
    return {
        "answer": "Не удалось надёжно подтвердить ответ материалами базы. Уточните вопрос или обратитесь в HR.",
        "sources": [],
        "grounded": False,
        "escalation_suggested": True,
        "mode": "refusal",
    }


def answer_from_knowledge(
    question: str, articles: list[dict], reader: LocalReader
) -> dict:
    bundle = prepare_evidence(articles)
    if not bundle.spans:
        return unavailable_evidence()
    if not _INFERENCE.acquire(timeout=2):
        raise JanaUnavailable("Local reader is busy")
    try:
        context = json.loads(bundle.prompt_text)["articles"]
        decision = reader.select(question, context)
        # Validate provenance in code. A second judgment by the same model is
        # not independent verification of meaning and can discard valid evidence.
        sources = (
            select_excerpts(bundle, decision.evidence_ids)
            if decision.evidence_ids
            else []
        )
        prefix = framing_for(decision)
        if sources and all(source["title"].startswith("Демо:") for source in sources):
            prefix = (prefix + "\n\n" if prefix else "") + "Демонстрационные материалы:"
        answer = prefix
        if sources:
            answer += ("\n\n" if answer else "") + "\n\n".join(
                f"{source['excerpt']} [{i}]" for i, source in enumerate(sources, 1)
            )
        return {
            "answer": answer,
            "sources": sources,
            "grounded": bool(sources),
            "escalation_suggested": decision.kind not in {"answer", "clarify"},
            "mode": "excerpts" if sources else "refusal",
        }
    except (InvalidDecision, ValueError):
        logger.info("Jana rejected an invalid local evidence selection")
        return unavailable_evidence()
    finally:
        _INFERENCE.release()
