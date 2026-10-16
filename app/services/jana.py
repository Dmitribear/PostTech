import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from openai import OpenAI, OpenAIError

from app.core.config import get_settings
from app.db.supabase import get_supabase_client


@dataclass(frozen=True)
class _FaqIntent:
    questions: tuple[str, ...]
    evidence: tuple[str, ...]


# These grammars describe questions covered by the published demo FAQ. Matching
# the whole question rejects unknown conditions and personal-data requests even
# when they share a topic with a published article. New FAQ topics should add
# question patterns and the evidence required in the actual article together.
_HOW = r"как (?:мне |можно |я могу )?"
_WHERE = r"(?:где|как) (?:мне |можно |я могу )?"
_APPLICATION = r"(?:заявку|заявление) на "
_VIEW = r"(?:посмотреть|проверить|узнать|найти|увидеть) "
_ROLE = r"(?:сотрудника|работника|руководителя|менеджера|hr|hr администратора)"
_INTENTS = (
    _FaqIntent(
        questions=(
            _HOW + r"(?:подать|создать|оформить|отправить) " + _APPLICATION + r"отпуск",
            _HOW + r"(?:запросить|оформить|взять) отпуск",
            _HOW + r"уйти в отпуск",
            r"как подается заявка на отпуск",
        ),
        evidence=(r"отпуск", r"заявк", r"(?:дат[ауые]|запросить|оформить)"),
    ),
    _FaqIntent(
        questions=(
            _HOW + r"(?:подать|создать|оформить|отправить) " + _APPLICATION + r"аванс",
            _HOW + r"(?:запросить|оформить|получить) аванс",
            r"как подается заявка на аванс",
        ),
        evidence=(r"аванс", r"заявк", r"(?:сумм|запросить|оформить)"),
    ),
    _FaqIntent(
        questions=(
            _WHERE + _VIEW + r"(?:текущий )?статус (?:моей |своей )?заявки",
            _HOW + r"(?:отследить|отслеживать) статус (?:моей |своей )?заявки",
            r"где (?:отображается|показан|виден) статус (?:моей |своей )?заявки",
            r"где (?:посмотреть|найти) (?:мои |свои )?заявки",
        ),
        evidence=(r"статус", r"заявк", r"раздел"),
    ),
    _FaqIntent(
        questions=(
            _WHERE + _VIEW + r"(?:мой |свой )?остаток (?:отпуска|отпускных дней|дней отпуска)",
            r"где (?:отображается|показан|виден) остаток (?:отпуска|отпускных дней|дней отпуска)",
            _WHERE + _VIEW + r"(?:сколько|количество) (?:у меня )?(?:осталось )?дней отпуска",
        ),
        evidence=(r"остаток", r"отпуск", r"профил"),
    ),
    _FaqIntent(
        questions=(
            r"какие права (?:доступа )?(?:есть )?у " + _ROLE,
            r"(?:какие данные|какая информация) (?:доступны|доступна) (?:сотруднику|работнику|руководителю|менеджеру|hr|hr администратору)",
            r"(?:какие данные|что) (?:может видеть|может просматривать|может смотреть|видит) (?:сотрудник|работник|руководитель|менеджер|hr|hr администратор)",
            r"к каким данным у " + _ROLE + r" (?:есть )?доступ",
            r"кто (?:видит|может видеть|имеет доступ к) (?:мои|моим|кадровые|кадровым|персональные|персональным) (?:данные|данным)",
            r"какие (?:есть )?правила доступа к (?:кадровым|персональным) данным",
            r"может ли (?:сотрудник|работник|руководитель|менеджер) видеть (?:чужие данные|данные (?:коллег|других сотрудников))",
        ),
        evidence=(r"сотрудник", r"руководитель", r"команд", r"данн"),
    ),
)


def _normalize_question(question: str) -> str:
    normalized = re.sub(r"\s+", " ", question.casefold().replace("ё", "е")).strip()
    normalized = normalized.rstrip("?!.").strip()
    normalized = re.sub(
        r"^(?:подскажите|подскажи|скажите|скажи)(?:,? пожалуйста)?[, :]+",
        "",
        normalized,
    )
    return re.sub(r",? пожалуйста$", "", normalized).strip()


def _find_intent(question: str) -> _FaqIntent | None:
    normalized = _normalize_question(question)
    return next(
        (
            intent
            for intent in _INTENTS
            if any(re.fullmatch(pattern, normalized) for pattern in intent.questions)
        ),
        None,
    )


def _rank_articles(question: str, articles: Iterable[dict]) -> list[dict]:
    intent = _find_intent(question)
    if intent is None:
        return []
    # A matching title/keyword alone cannot establish support for the answer.
    return [
        article
        for article in articles
        if all(
            re.search(pattern, str(article.get("content", "")).casefold())
            for pattern in intent.evidence
        )
    ][:3]


def _source_payload(articles: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "article_id": str(article["id"]),
            "title": str(article["source_title"]),
            "url": article.get("source_url") or f"/api/v1/ai/sources/{article['id']}",
        }
        for article in articles
    ]


def _no_answer() -> dict:
    return {
        "answer": "В базе Jana нет подтверждённой информации по этому вопросу. Обратитесь в HR.",
        "sources": [],
        "grounded": False,
        "escalation_suggested": True,
    }


def _answer(articles: list[dict], excerpts: list[str]) -> dict:
    return {
        "answer": "Из опубликованной базы знаний Jana:\n\n" + "\n\n".join(excerpts),
        "sources": _source_payload(articles),
        "grounded": True,
        "escalation_suggested": False,
    }


def _citation_chunks(article: dict) -> list[str]:
    # Complete sentences preserve qualifications/negations. An arbitrary
    # substring could drop "only", "not", or the employee/team scope.
    content = str(article["content"]).strip()
    return [chunk for chunk in re.split(r"(?<=[.!?])\s+", content) if chunk]


def _model_answer(question: str, articles: list[dict]) -> dict | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    materials = [
        {"article_id": str(article["id"]), "quotes": _citation_chunks(article)}
        for article in articles
    ]
    try:
        response = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=10,
            max_retries=0,
        ).chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты Jana. Выбери только готовые цитаты, отвечающие на вопрос, без изменений. "
                        "Верни JSON: {\"status\":\"supported\",\"quotes\":["
                        "{\"article_id\":\"ID\",\"quote\":\"точная готовая цитата\"}]}. "
                        "Не дополняй и не сокращай цитаты. Не придумывай правил или персональных данных. "
                        "Если ответа нет, верни {\"status\":\"unsupported\",\"quotes\":[]}."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "materials": materials}, ensure_ascii=False
                    ),
                },
            ],
        )
        if not response.choices:
            return None
        selection = json.loads(response.choices[0].message.content or "")
    except (OpenAIError, ValueError, TypeError):
        return None

    if not isinstance(selection, dict) or set(selection) != {"status", "quotes"}:
        return None
    if selection["status"] == "unsupported" and selection["quotes"] == []:
        return _no_answer()
    quotes = selection["quotes"]
    if selection["status"] != "supported" or not isinstance(quotes, list) or not 1 <= len(quotes) <= 8:
        return None

    by_id = {str(article["id"]): article for article in articles}
    selected_articles: dict[str, dict] = {}
    excerpts = []
    for item in quotes:
        if not isinstance(item, dict) or set(item) != {"article_id", "quote"}:
            return None
        article_id, quote = item["article_id"], item["quote"]
        if not isinstance(article_id, str) or not isinstance(quote, str):
            return None
        article = by_id.get(article_id)
        if article is None or quote not in _citation_chunks(article):
            return None
        selected_articles[article_id] = article
        if quote not in excerpts:
            excerpts.append(quote)
    # Reject a valid but irrelevant quote selected from an otherwise useful article.
    if not _rank_articles(question, [{"content": " ".join(excerpts)}]):
        return None
    return _answer(list(selected_articles.values()), excerpts)


def get_source_article(article_id: str) -> dict | None:
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
    if _find_intent(question) is None:
        return _no_answer()
    result = (
        get_supabase_client()
        .table("knowledge_articles")
        .select("id,title,content,source_title,source_url")
        .eq("active", True)
        .limit(200)
        .execute()
    )
    articles = _rank_articles(question, result.data or [])
    if not articles:
        return _no_answer()
    model_answer = _model_answer(question, articles)
    if model_answer is not None:
        return model_answer
    return _answer(articles, [str(article["content"]) for article in articles])
