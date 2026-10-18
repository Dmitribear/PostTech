"""Conservative local FAQ retrieval. Every factual answer is a curated quote."""

import hashlib
from functools import lru_cache
from pathlib import Path
from threading import Lock
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.knowledge.jana_errors import JanaUnavailable
from app.domain.knowledge.jana_guardrails import card_is_applicable, refusal_reason
from app.domain.knowledge.jana_text import normalize_question
from app.infrastructure.ai.local_embeddings import LocalEmbedder

MAX_ARTICLES = 100
MAX_EXCERPT_LENGTH = 1000
_LOAD_LOCK = Lock()


class FAQCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    article_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    questions: list[str] = Field(min_length=1, max_length=20)
    excerpt: str = Field(min_length=1, max_length=MAX_EXCERPT_LENGTH)


class FAQCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    demo: bool
    notice: str
    cards: list[FAQCard] = Field(min_length=1, max_length=200)
    unsupported_questions: list[str] = Field(min_length=1, max_length=500)


def refuse(message: str = "В базе нет подтверждённого ответа. Уточните у HR.") -> dict:
    return {
        "answer": message,
        "sources": [],
        "grounded": False,
        "escalation_suggested": True,
        "mode": "refusal",
    }


class FAQIndex:
    def __init__(self, catalog: FAQCatalog, embedder):
        if len({card.id for card in catalog.cards}) != len(catalog.cards):
            raise JanaUnavailable("Duplicate FAQ card IDs")
        self.catalog = catalog
        self.embedder = embedder
        self.owners: list[int] = []
        texts = []
        for index, card in enumerate(catalog.cards):
            texts.extend(card.questions)
            self.owners.extend([index] * len(card.questions))
        texts.extend(catalog.unsupported_questions)
        self.owners.extend([-1] * len(catalog.unsupported_questions))
        try:
            self.vectors = embedder.encode(texts)
        except ValueError as exc:
            raise JanaUnavailable("Invalid FAQ question length") from exc

    def rank(self, question: str) -> list[tuple[int, float]]:
        similarities = self.vectors @ self.embedder.encode([question])[0]
        scores: dict[int, float] = {}
        for owner, score in zip(self.owners, similarities, strict=True):
            scores[owner] = max(scores.get(owner, -1.0), float(score))
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)


@lru_cache(maxsize=1)
def _load_index(model_dir: Path, faq_path: Path) -> FAQIndex:
    try:
        catalog = FAQCatalog.model_validate_json(faq_path.read_text(encoding="utf-8"))
        return FAQIndex(catalog, LocalEmbedder(model_dir))
    except (OSError, ValidationError, ValueError) as exc:
        raise JanaUnavailable("Local FAQ catalog is unavailable") from exc


def get_index(settings) -> FAQIndex:
    # Avoid two simultaneous first requests loading a second model into RAM.
    with _LOAD_LOCK:
        return _load_index(settings.jana_model_dir, settings.jana_faq_path)


def answer_from_faq(
    question: str,
    articles: list[dict],
    index: FAQIndex,
    min_score: float = 0.72,
    margin: float = 0.045,
) -> dict:
    if len(articles) > MAX_ARTICLES:
        raise JanaUnavailable("Knowledge base exceeds the supported article limit")
    if reason := refusal_reason(question, clarify_request_kind=False):
        return refuse(reason)
    question = normalize_question(question)
    # Repairing a typo must never remove a scope restriction. The original
    # question and the conservatively repaired text both pass the same checks.
    if reason := refusal_reason(question):
        return refuse(reason)
    try:
        ranked = index.rank(question)
    except ValueError:
        return refuse(
            "Сократите вопрос: я могу подобрать ответ на один короткий вопрос."
        )
    # Remove only semantically incompatible positive candidates before comparing
    # confidence. A competing unsupported intent must always keep its score.
    ranked = [
        (owner, score)
        for owner, score in ranked
        if owner == -1 or card_is_applicable(question, index.catalog.cards[owner].id)
    ]
    if not ranked:
        return refuse()
    winner, score = ranked[0]
    if winner == -1 or score < min_score:
        return refuse()
    runner_up, next_score = ranked[1] if len(ranked) > 1 else (-1, -1.0)
    if score - next_score < margin:
        if runner_up >= 0 and next_score >= min_score:
            first = index.catalog.cards[winner].questions[0]
            second = index.catalog.cards[runner_up].questions[0]
            return refuse(f"Уточните, что вас интересует: «{first}» или «{second}»?")
        return refuse()

    card = index.catalog.cards[winner]
    matches = [
        a
        for a in articles
        if str(a["id"]) == str(card.article_id) and a.get("active") is not False
    ]
    if len(matches) != 1 or card.excerpt not in matches[0].get("content", ""):
        # An outdated/unpublished source invalidates the card, not a license
        # to substitute the next similar answer or a stale cached quote.
        return refuse("Источник ответа изменился или недоступен. Уточните у HR.")
    article = matches[0]
    if (
        hashlib.sha256(article["content"].encode("utf-8")).hexdigest()
        != card.source_sha256
    ):
        # A changed qualification elsewhere in the article can invalidate an
        # unchanged quote. Require review of the whole source, not just a span.
        return refuse("Источник ответа изменился. Карточку должен проверить HR.")
    prefix = (
        "Демо: "
        if index.catalog.demo and not card.excerpt.startswith("В демо-прототипе")
        else ""
    )
    return {
        "answer": f"{prefix}{card.excerpt} [1]",
        "sources": [
            {
                "id": str(card.article_id),
                "title": article["source_title"],
                "url": f"/api/v1/ai/local/sources/{card.article_id}",
                "excerpt": card.excerpt,
            }
        ],
        "grounded": True,
        "escalation_suggested": False,
        "mode": "excerpts",
    }
