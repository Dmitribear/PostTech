import re
from collections.abc import Iterable

from openai import OpenAI
from openai import OpenAIError

from app.core.config import get_settings
from app.db.supabase import get_supabase_client

_TOKEN_RE = re.compile(r"[\w\u0400-\u04ff]{3,}", re.IGNORECASE)
_STOP_WORDS = {
    "and", "are", "for", "how", "the", "what", "when", "where", "with",
    "это", "как", "где", "для", "или", "мне", "можно", "могу", "нужно", "что",
    "это", "есть", "если", "почему", "когда", "какой", "какая", "мне",
}


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value) if token.casefold() not in _STOP_WORDS}


def _rank_articles(question: str, articles: Iterable[dict]) -> list[dict]:
    question_tokens = _tokens(question)
    if not question_tokens:
        return []

    ranked: list[tuple[int, dict]] = []
    for article in articles:
        title_tokens = _tokens(str(article.get("title", "")))
        content_tokens = _tokens(str(article.get("content", "")))
        keyword_tokens = _tokens(" ".join(article.get("keywords") or []))
        score = (
            3 * len(question_tokens & title_tokens)
            + 2 * len(question_tokens & keyword_tokens)
            + len(question_tokens & content_tokens)
        )
        if score:
            ranked.append((score, article))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < max(1, len(question_tokens) // 4):
        return []
    best_score = ranked[0][0]
    return [article for score, article in ranked if score >= max(1, best_score // 2)][:3]


def _source_payload(articles: list[dict]) -> list[dict[str, str | None]]:
    return [
        {
            "title": str(article["source_title"]),
            "url": article.get("source_url"),
        }
        for article in articles
    ]


def answer_question(question: str) -> dict:
    result = (
        get_supabase_client()
        .table("knowledge_articles")
        .select("title,content,source_title,source_url,keywords")
        .eq("active", True)
        .limit(200)
        .execute()
    )
    articles = _rank_articles(question, result.data or [])
    if not articles:
        return {
            "answer": "В базе Jana нет подтверждённой информации по этому вопросу. Обратитесь в HR.",
            "sources": [],
            "grounded": False,
            "escalation_suggested": True,
        }

    settings = get_settings()
    if settings.openai_api_key:
        context = "\n\n".join(
            f"Источник: {article['source_title']}\nМатериал: {str(article['content'])[:5000]}"
            for article in articles
        )
        try:
            response = OpenAI(
                api_key=settings.openai_api_key.get_secret_value()
            ).chat.completions.create(
                model=settings.openai_model,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты Jana, HR-помощник. Отвечай только фактами из переданных материалов. "
                            "Не придумывай правила, персональные данные или кадровые решения. "
                            "Если материалов недостаточно, прямо скажи об этом и предложи обратиться в HR. "
                            "Отвечай на языке вопроса. Источники будут перечислены отдельно API."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Вопрос сотрудника:\n{question}\n\nМатериалы базы знаний:\n{context}",
                    },
                ],
            )
            answer = response.choices[0].message.content
            if answer:
                return {
                    "answer": answer,
                    "sources": _source_payload(articles),
                    "grounded": True,
                    "escalation_suggested": False,
                }
        except OpenAIError:
            pass

    excerpts = "\n\n".join(
        f"{article['source_title']}: {str(article['content'])[:900]}"
        for article in articles
    )
    return {
        "answer": f"Привожу найденный фрагмент базы знаний (AI-генерация сейчас недоступна):\n\n{excerpts}",
        "sources": _source_payload(articles),
        "grounded": True,
        "escalation_suggested": False,
    }
