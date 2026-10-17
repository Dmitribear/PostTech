"""Read-only, published knowledge boundary for the authenticated local Jana API."""
from fastapi import HTTPException
from app.core.config import get_settings
from app.db.supabase import get_supabase_client
from app.services.jana_evidence import MAX_ARTICLES
from app.services.jana_errors import JanaUnavailable
from app.services.jana_reader import LocalReader, answer_from_knowledge
from app.services.jana_knowledge import FIELDS, metadata, public_article, snapshot_version, usable


def get_source_article(article_id: str, version: str | None = None) -> dict | None:
    rows = (get_supabase_client().table("knowledge_articles").select(FIELDS)
            .eq("id", article_id).eq("active", True).limit(1).execute().data) or []
    if not rows or not usable(rows[0]):
        return None
    article = rows[0]
    if version is not None and version != snapshot_version(article):
        raise HTTPException(409, "Источник обновлён. Задайте вопрос заново.")
    return public_article(article)


def _published_articles() -> list[dict]:
    rows = (get_supabase_client().table("knowledge_articles").select(FIELDS)
            .eq("active", True).order("id").limit(MAX_ARTICLES + 1).execute().data) or []
    if len(rows) > MAX_ARTICLES:
        raise JanaUnavailable("Knowledge base exceeds the supported article limit")
    return [article for article in rows if usable(article)]


def answer_question(question: str, language: str = "ru") -> dict:
    articles = _published_articles()
    answer = answer_from_knowledge(question, articles, LocalReader(get_settings()))
    if _published_articles() != articles:
        raise JanaUnavailable("Knowledge changed during inference; retry")
    indexed = {str(article["id"]): article for article in articles}
    for source in answer["sources"]:
        source.update(metadata(indexed[str(source["id"])]))
        source["url"] += "?version=" + source["version"]
    # Evidence remains a verbatim quote; no unverified machine translation.
    if language == "kk":
        answer["answer"] = "Дереккөздер мен жауаптың түпнұсқа тілі — орыс тілі.\n\n" + answer["answer"]
    return answer
