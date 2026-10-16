"""Read-only knowledge storage boundary for the authenticated Jana API."""

from app.core.config import get_settings
from app.db.supabase import get_supabase_client
from app.services.jana_local import MAX_ARTICLES, answer_from_faq, get_index


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


def answer_question(question: str) -> dict:
    result = (
        get_supabase_client()
        .table("knowledge_articles")
        .select("id,title,content,source_title,source_url")
        .eq("active", True)
        .order("id")
        .limit(MAX_ARTICLES + 1)
        .execute()
    )
    settings = get_settings()
    return answer_from_faq(question, result.data or [], get_index(settings),
                           settings.jana_min_score, settings.jana_score_margin)
