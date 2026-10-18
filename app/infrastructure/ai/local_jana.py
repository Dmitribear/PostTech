"""Read-only, published knowledge boundary for the authenticated local Jana API."""

from fastapi import HTTPException

from app.domain.knowledge.jana_errors import JanaUnavailable
from app.domain.knowledge.jana_evidence import MAX_ARTICLES
from app.domain.knowledge.publication import (
    FIELDS,
    metadata,
    public_article,
    snapshot_version,
    usable,
)
from app.infrastructure.ai.jana_reader import LocalReader, answer_from_knowledge
from app.infrastructure.ai.jana_runtime import (
    reader_runtime,
    response_cache,
    snapshot_identity,
)
from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client


def get_source_article(article_id: str, version: str | None = None) -> dict | None:
    rows = (
        get_supabase_client()
        .table("knowledge_articles")
        .select(FIELDS)
        .eq("id", article_id)
        .eq("active", True)
        .limit(1)
        .execute()
        .data
    ) or []
    if not rows or not usable(rows[0]):
        return None
    article = rows[0]
    if version is not None and version != snapshot_version(article):
        raise HTTPException(409, "Источник обновлён. Задайте вопрос заново.")
    return public_article(article)


def _published_articles() -> list[dict]:
    rows = (
        get_supabase_client()
        .table("knowledge_articles")
        .select(FIELDS)
        .eq("active", True)
        .order("id")
        .limit(MAX_ARTICLES + 1)
        .execute()
        .data
    ) or []
    if len(rows) > MAX_ARTICLES:
        raise JanaUnavailable("Knowledge base exceeds the supported article limit")
    return [article for article in rows if usable(article)]


def answer_question(question: str, language: str = "ru") -> dict:
    articles = _published_articles()
    settings = get_settings()
    reader = LocalReader(settings)
    ttl = getattr(settings, "jana_response_cache_ttl_seconds", 0)
    if ttl > 0:
        identity = reader_runtime.reader_identity(reader)

        def compute():
            result = answer_from_knowledge(question, articles, reader)
            if _published_articles() != articles:
                raise JanaUnavailable("Knowledge changed during inference; retry")
            return result

        answer = response_cache.get_or_compute(
            (question, snapshot_identity(articles), identity),
            compute,
            ttl=ttl,
            max_entries=settings.jana_response_cache_max_entries,
            wait_seconds=reader.timeout + 5,
        )
    else:
        answer = answer_from_knowledge(question, articles, reader)
    if _published_articles() != articles:
        raise JanaUnavailable("Knowledge changed during inference; retry")
    indexed = {str(article["id"]): article for article in articles}
    for source in answer["sources"]:
        source.update(metadata(indexed[str(source["id"])]))
        source["url"] += "?version=" + source["version"]
    # Evidence remains a verbatim quote; no unverified machine translation.
    if language == "kk":
        answer["answer"] = (
            "Дереккөздер мен жауаптың түпнұсқа тілі — орыс тілі.\n\n" + answer["answer"]
        )
    return answer


def runtime_status() -> dict:
    return reader_runtime.status()
