"""Read-only knowledge storage boundary for the authenticated Jana API."""

from app.core.config import get_settings
from app.db.supabase import get_supabase_client
from app.services.jana_evidence import MAX_ARTICLES
from app.services.jana_errors import JanaUnavailable
from app.services.jana_reader import LocalReader, answer_from_knowledge


def get_source_article(article_id: str) -> dict | None:
    """Only published, company-wide FAQ articles belong in this table."""
    result = (
        get_supabase_client()
        .table("knowledge_articles")
        .select("id,title,content,source_title,source_url")
        .eq("id", article_id)
        .eq("active", True)
        .limit(1)
        .execute()
    )
    return (result.data or [None])[0]


def _published_articles() -> list[dict]:
    result = (
        get_supabase_client()
        .table("knowledge_articles")
        .select("id,title,content,source_title,source_url")
        .eq("active", True)
        .order("id")
        .limit(MAX_ARTICLES + 1)
        .execute()
    )
    return result.data or []


def answer_question(question: str) -> dict:
    articles = _published_articles()
    settings = get_settings()
    answer = answer_from_knowledge(question, articles, LocalReader(settings))
    # A publication or an exception elsewhere in a source may change while the
    # local model reads it. Never serve an answer from that obsolete snapshot.
    if _published_articles() != articles:
        raise JanaUnavailable("Knowledge changed during inference; retry")
    return answer
