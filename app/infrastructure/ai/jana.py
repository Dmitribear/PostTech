import json
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException
from openai import OpenAI, OpenAIError

from app.domain.knowledge.jana_errors import JanaUnavailable
from app.infrastructure.ai.jana_actions import (
    ACTION_ROUTES,
    action_buttons,
    localize_ui_captions,
    source_action_ids,
)
from app.infrastructure.ai.jana_agent import _INJECTION
from app.infrastructure.ai.jana_conditions import (
    missing_policy_answer,
    retain_leave_conditions,
    retain_portal_terms,
)
from app.infrastructure.ai.jana_prompts import ANSWER_INSTRUCTIONS, VERIFY_INSTRUCTIONS, KAZAKH_TRANSLATION_INSTRUCTIONS
from app.infrastructure.ai.jana_scope import classify_scope
from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client

_TOKEN_RE = re.compile(r"[\w\u0400-\u04ff]{3,}", re.IGNORECASE)
_STOP_WORDS = {
    "and",
    "are",
    "for",
    "how",
    "the",
    "what",
    "where",
    "with",
    "это",
    "как",
    "где",
    "для",
    "или",
    "мне",
    "можно",
    "могу",
    "нужно",
    "что",
    "это",
    "есть",
    "если",
    "какой",
    "какая",
    "мне",
    "мои",
    "мой",
    "свою",
    "свой",
    "моей",
    "мою",
    "мое",
    "моего",
    "моих",
    "своих",
    "своей",
    "хочу",
    "куда",
    "чего",
    "начала",
    "потом",
    "после",
    "этого",
    "про",
    "меня",
    "нужен",
    "нужна",
    "ли",
    "бы",
    "the",
    "can",
    "get",
    "want",
    "who",
    "see",
    "my",
    "please",
    "кто",
    "моим",
    "через",
}
_PROCEDURAL_WORDS = {
    "подскажи",
    "подскажите",
    "объясни",
    "объясните",
    "порядок",
    "портал",
    "портале",
    "подать",
    "оформить",
    "создать",
    "запросить",
    "отправить",
    "посмотреть",
    "узнать",
    "получить",
    "пожалуйста",
    "расскажи",
    "расскажите",
    "показать",
    "submit",
    "create",
    "request",
    "please",
    "tell",
    "about",
    "apply",
    "взять",
    "уйти",
    "начать",
    "найти",
    "искать",
    "проверить",
    "отследить",
    "check",
}
_UNSAFE_REQUEST = re.compile(
    r"игнорир\w*|игнор\w*\s+инструкц|забудь\s+(?:правила|инструкции)|"
    r"(?:ignore|override|disregard)\s+(?:all\s+|previous\s+|the\s+|system\s+)*instructions|"
    r"system\s*prompt|системн\w*\s+(?:промпт|инструкц)|"
    r"\b(?:одобри|одобрите|согласуй|согласуйте|утверди|утвердите|уволь|увольте|отклони|отклоните|назначь)\b|"
    r"\b(?:approve|reject|fire|dismiss)\s+(?:my|this|the|an?|employee|request)\b",
    re.IGNORECASE,
)
_ACTION_COMMAND = re.compile(r"\b(?:отмени|отмените|создай|создайте|измени|измените|оформи|оформите)\b", re.I)
_PRIVATE_REQUEST = re.compile(
    r"зарплат\w*|оклад\w*|\bиин\b|паспорт\w*|телефон\w*|домашн\w*\s+адрес|"
    r"диагноз\w*|больничн\w*\s+(?:коллег|сотрудник)|чуж\w*\s+(?:данн|профил|заявк)|"
    r"(?:покажи|выдай|скачай|дай)\s+(?:(?:мне|все|всех)\s+)*(?:профил\w*|данн\w*\s+сотрудник)|"
    r"\b(?:salary|salaries|passport|medical|ssn)\b|[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    re.I,
)
# Narrow vocabulary normalization improves ordinary phrasing without inferring HR rules.
_CONCEPTS = (
    (r"отпуск\w*|отдохнуть|отдых|vacation|leave", "отпуск"),
    (r"аванс\w*|advance", "аванс"),
    (r"заявк\w*|заявлен\w*|обращен\w*|application|requests?", "заявка"),
    (r"статус\w*|состояни\w*|status", "статус"),
    (r"руководител\w*|начальник\w*|manager", "руководитель"),
    (r"данн\w*|сведени\w*|data", "данные"),
    (r"кадров\w*|персональн\w*|personal", "кадровые"),
    (r"профил\w*|profile", "профиль"),
    (r"доступ\w*|access", "доступ"),
    (r"команд\w*|подчиненн\w*|team", "команда"),
    (r"сотрудник\w*|работник\w*|employee", "сотрудник"),
    (r"остат\w*|остал\w*|remaining|balance", "остаток"),
    (r"дней|дня|дни|days?", "дни"),
    (
        r"оформ\w*|пода\w*|запроси\w*|отправ\w*|созда\w*|подать|запросить|submit|apply|create",
        "оформить",
    ),
    (
        r"посмотр\w*|смотр\w*|увид\w*|узна\w*|провер\w*|отсле\w*|найти|view|check|track",
        "посмотреть",
    ),
)
_ARTICLE_FIELDS = "id,title,content,source_title,source_url,keywords,updated_at,reviewed_at,review_due_at,version"
_REFUSAL = (
    "В базе Jana нет подтверждённой информации по этому вопросу. Обратитесь в HR."
)
_LOG = logging.getLogger(__name__)


def _format(name: str, properties: dict) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


_ANSWER_FORMAT = _format(
    "jana_answer",
    {
        "supported": {"type": "boolean"},
        "reason": {"type": "string", "enum": ["supported", "missing_information", "out_of_scope", "personal_data", "action_request", "instructions"]},
        "answer": {"type": "string"},
        "actions": {"type": "array", "items": {"type": "string", "enum": list(ACTION_ROUTES)}},
        "passage_ids": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "integer"},
        },
    },
)
_CHECK_FORMAT = _format("jana_evidence_check", {"supported": {"type": "boolean"}, "answer": {"type": "string"}})


def _refuse(message: str = _REFUSAL, reason: str = "missing_information") -> dict:
    if reason == "out_of_scope":
        message = "Я помогаю с отпуском, заявками, обучением и другими функциями PostTech. На посторонние вопросы не отвечаю."
    return {
        "answer": message,
        "sources": [],
        "grounded": False,
        "escalation_suggested": reason != "out_of_scope",
        "mode": "refusal",
        "reason": reason,
        "actions": [],
    }


def _tokens(value: str) -> set[str]:
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"\bкто\s+(?:может\s+)?вид(?:ит|еть)\b", "доступ", value)
    value = re.sub(r"\bимеет\s+доступ\b", "доступ", value)
    tokens = set()
    for token in _TOKEN_RE.findall(value):
        if token in _STOP_WORDS:
            continue
        tokens.add(
            next(
                (
                    concept
                    for pattern, concept in _CONCEPTS
                    if re.fullmatch(pattern, token)
                ),
                token,
            )
        )
    return tokens


def _source_freshness(article: dict) -> dict:
    reviewed = article.get("reviewed_at")
    due = article.get("review_due_at")
    status = "unverified"
    try:
        if reviewed:
            reviewed_date = datetime.fromisoformat(str(reviewed).replace("Z", "+00:00"))
            if reviewed_date.tzinfo is None:
                reviewed_date = reviewed_date.replace(tzinfo=timezone.utc)
            if reviewed_date <= datetime.now(timezone.utc):
                status = "reviewed"
                if due:
                    due_date = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                    if due_date.tzinfo is None:
                        due_date = due_date.replace(tzinfo=timezone.utc)
                    if due_date <= datetime.now(timezone.utc):
                        status = "review_overdue"
    except (ValueError, TypeError):
        status = "unverified"
    return {
        "version": article.get("version"),
        "updated_at": article.get("updated_at"),
        "reviewed_at": reviewed,
        "review_due_at": due,
        "freshness": status,
    }


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
    return [article for score, article in ranked if score >= max(1, best_score // 2)][
        :3
    ]


def _source_payload(articles: list[dict]) -> list[dict[str, str | None]]:
    return [
        {
            "id": str(article["id"]),
            "title": str(article["source_title"]),
            "url": _safe_source_url(article.get("source_url")),
            **_source_freshness(article),
        }
        for article in articles
    ]


def _safe_source_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"https", "http"} and parsed.netloc else None
    except ValueError:
        return None


def get_source(source_id: UUID, version: str | None = None) -> dict:
    """Published knowledge is shared by all signed-in roles; no HR records enter it."""
    rows = (
        get_supabase_client()
        .table("knowledge_articles")
        .select(_ARTICLE_FIELDS)
        .eq("id", str(source_id))
        .eq("active", True)
        .limit(1)
        .execute()
        .data
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    source = dict(rows[0])
    if version is not None and str(source.get("version")) != version:
        raise HTTPException(
            409,
            "Источник обновлён. Задайте вопрос заново, чтобы получить ответ по новой версии.",
        )
    source.pop("keywords", None)
    source["source_url"] = _safe_source_url(source.get("source_url"))
    source.update(_source_freshness(source))
    return source


def _covers_question(question: str, articles: list[dict]) -> bool:
    """Conservative lexical fallback: a topic match alone is not an answer."""
    terms = _tokens(question) - _PROCEDURAL_WORDS
    # One source must cover the question; joining unrelated fragments is insufficient.
    return bool(terms) and any(
        terms <= _tokens(f"{a['title']} {a['content']}") for a in articles
    )


def _validated_excerpts(
    raw: str, articles: list[dict]
) -> tuple[list[dict], list[str]] | None:
    """Never treat free-form model prose or invented citations as grounded."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("supported") is not True:
            return None
        if "passage_ids" in payload:
            ids = payload["passage_ids"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 6:
                return None
            if any(type(i) is not int or not 0 <= i < len(articles) for i in ids):
                return None
            selected = [articles[i] for i in dict.fromkeys(ids)]
            return selected, [f"{a['source_title']}: {a['content']}" for a in selected]
        excerpts = payload.get("excerpts")
        if not isinstance(excerpts, list) or not 1 <= len(excerpts) <= 6:
            return None
        selected, quotes = [], []
        for excerpt in excerpts:
            if not isinstance(excerpt, dict):
                return None
            index, quote = excerpt.get("source_index"), excerpt.get("quote")
            if type(index) is not int or not 0 <= index < len(articles):
                return None
            if not isinstance(quote, str) or not 20 <= len(quote.strip()) <= 3000:
                return None
            article = articles[index]
            if quote not in str(article["content"]) or _INJECTION.search(
                quote
            ):
                return None
            if article not in selected:
                selected.append(article)
            quotes.append(f"{article['source_title']}: {quote}")
        return selected, quotes
    except (ValueError, TypeError):
        return None


def _generated_answer(payload: dict, quotes: list[str]) -> str | None:
    answer = payload.get("answer")
    if not isinstance(answer, str) or not 15 <= len(answer.strip()) <= 1800:
        return None
    if (
        _UNSAFE_REQUEST.search(answer)
        or re.search(r"https?://|www\.", answer, re.I)
    ):
        return None
    # Dates, money and limits must not appear without literal evidence.
    if not set(re.findall(r"\d+(?:[.,]\d+)?", answer)) <= set(
        re.findall(r"\d+(?:[.,]\d+)?", " ".join(quotes))
    ):
        return None
    return answer.strip()


def answer_question(question: str, language: str = "ru", role: str = "worker") -> dict:
    procedure = re.search(r"\bкак\b.{0,70}(?:изменить|обновить|исправить).{0,50}(?:телефон|данные|профиль)", question, re.I)
    if language == "kk" and re.search(r"қалай.{0,50}(?:өзгерт|түзет|жаңарт)", question, re.I) and re.search(r"телефон|профил|дерек", question, re.I):
        procedure = True
    if _PRIVATE_REQUEST.search(question) and not procedure:
        return _refuse(
            "Jana не ищет личные сведения сотрудников. Свои данные доступны в профиле, по кадровому вопросу обратитесь в HR."
        )
    if _UNSAFE_REQUEST.search(question) or _ACTION_COMMAND.search(question):
        return _refuse(
            "Jana объясняет опубликованные HR-правила, но не раскрывает служебные инструкции "
            "и не принимает кадровых решений. Для согласования заявки обратитесь к руководителю или HR."
        )
    result = (
        get_supabase_client()
        .table("knowledge_articles")
        .select(_ARTICLE_FIELDS)
        .eq("active", True)
        .limit(200)
        .execute()
    )
    available = [
            article
            for article in result.data or []
            if not _INJECTION.search(str(article.get("content", "")))
            and _source_freshness(article)["freshness"] != "review_overdue"
    ]
    if not available:
        return _refuse()
    settings = get_settings()
    model = (getattr(settings, "jana_kazakh_model", None) if language == "kk" else None) or settings.openai_model
    fallback_reason = "not_configured"
    if settings.openai_api_key and settings.openai_api_key.get_secret_value().strip():
        if len(available) > 100 or sum(len(str(a["content"])) for a in available) > 60000:
            raise JanaUnavailable("Knowledge base exceeds semantic context budget")
        articles = [
            {**article, "content": paragraph, "full_content": article["content"]}
            for article in available
            for paragraph in str(article["content"]).split("\n\n")
            if paragraph.strip()
        ]
        context = [
            {"source_index": index, "content": str(article["content"])}
            for index, article in enumerate(articles)
        ]
        client = None
        try:
            client = OpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                timeout=getattr(settings, "jana_model_timeout_seconds", 20.0),
                max_retries=0,
            )
            scope = (
                classify_scope(client, model, question, language="kk")
                if language == "kk" else classify_scope(client, model, question)
            )
            if scope["intent"] != "information":
                return _refuse(reason=scope["intent"])
            model_question = scope.get("question_ru", question)
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                store=False,
                max_completion_tokens=2400,
                response_format=_ANSWER_FORMAT,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            ANSWER_INSTRUCTIONS
                            + "\nThe scope check classified this as an informational question about the portal, not a command to perform an operation. Explain its procedure or rule using the sources.\n"
                            + "Ответ пиши на русском языке источников. Перевод для пользователя выполняется отдельным шагом."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"question": model_question, "original_question": question, "sources": context},
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            if response.choices and (
                getattr(response.choices[0], "finish_reason", "stop") != "stop"
                or getattr(response.choices[0].message, "refusal", None)
            ):
                return _refuse()
            raw = response.choices[0].message.content if response.choices else ""
            payload = json.loads(raw or "{}")
            if isinstance(payload, dict) and payload.get("supported") is False:
                return _refuse(reason=payload.get("reason", "missing_information"))
            validated = _validated_excerpts(raw or "", articles)
            if not validated:
                return _refuse()
            selected, quotes = validated
            answer = _generated_answer(json.loads(raw), quotes)
            if not answer:
                return _refuse()
            # A separate evidence check rejects unsupported paraphrases. It is a
            # model-based safeguard, not a mathematical proof of factuality.
            check = client.chat.completions.create(
                model=model,
                temperature=0,
                store=False,
                max_completion_tokens=1200,
                response_format=_CHECK_FORMAT,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            VERIFY_INSTRUCTIONS
                            + "\nWrite the verified answer in Russian. Translation is a separate step."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": model_question,
                                "original_question": question,
                                "answer": answer,
                                "evidence": quotes,
                                "sources": list(dict.fromkeys(a.get("full_content", a["content"]) for a in selected)),
                                "actions": payload.get("actions", []),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            if check.choices and (
                getattr(check.choices[0], "finish_reason", "stop") != "stop"
                or getattr(check.choices[0].message, "refusal", None)
            ):
                return _refuse()
            checked = (
                json.loads(check.choices[0].message.content or "{}")
                if check.choices
                else {}
            )
            if not isinstance(checked, dict) or checked.get("supported") is not True:
                return _refuse()
            answer = _generated_answer({"answer": checked.get("answer", answer)}, quotes)
            if not answer:
                return _refuse()
            if missing_policy_answer(model_question, answer):
                return _refuse()
            answer = retain_leave_conditions(answer, selected, "ru", model_question)
            answer = retain_portal_terms(answer, selected, "ru")
            if language == "kk":
                translation = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    store=False,
                    max_completion_tokens=1200,
                    response_format=_CHECK_FORMAT,
                    messages=[
                        {"role": "system", "content": KAZAKH_TRANSLATION_INSTRUCTIONS},
                        {"role": "user", "content": json.dumps({"text": answer}, ensure_ascii=False)},
                    ],
                )
                if not translation.choices or (
                    getattr(translation.choices[0], "finish_reason", "stop") != "stop"
                    or getattr(translation.choices[0].message, "refusal", None)
                ):
                    return _refuse()
                translated = json.loads(translation.choices[0].message.content or "{}") if translation.choices else {}
                if not isinstance(translated, dict) or translated.get("supported") is not True:
                    return _refuse()
                answer = _generated_answer(translated, quotes)
                if not answer or not re.search(r"[әғқңөұүһі]", answer, re.I):
                    return _refuse()
            answer = retain_portal_terms(answer, selected, language)
            answer = localize_ui_captions(answer, language)
            source_actions = source_action_ids(selected)
            scoped_actions = [
                action for action in scope.get("actions", [])
                if not source_actions or action in source_actions
            ]
            return {
                "answer": answer,
                "sources": _source_payload(list({a["id"]: a for a in selected}.values())),
                "grounded": True,
                "escalation_suggested": False,
                "mode": "generated",
                "actions": action_buttons(scoped_actions or source_actions[:1] or payload.get("actions", []), role, language),
            }
        except OpenAIError as exc:
            status = getattr(exc, "status_code", None)
            fallback_reason = {
                401: "authentication",
                403: "access",
                404: "model",
                429: "quota_or_rate_limit",
            }.get(status, "provider_unavailable")
            _LOG.warning("Jana generation fallback: %s", fallback_reason)
        except (ValueError, TypeError, IndexError):
            return _refuse()
        finally:
            if client is not None:
                client.close()

    articles = _rank_articles(question, [a for a in available if _covers_question(question, [a])])
    if not articles or not _covers_question(question, articles):
        return _refuse()
    # The best covering article is enough for the deterministic fallback. Lower
    # ranked pages often mention the same topic only to distinguish a workflow.
    articles = articles[:1]
    excerpts = "\n\n".join(
        f"{article['source_title']}: {str(article['content'])}"
        for article in articles
    )
    return {
        "answer": f"Привожу найденный фрагмент базы знаний (AI-генерация сейчас недоступна):\n\n{excerpts}",
        "sources": _source_payload(articles),
        "grounded": True,
        "escalation_suggested": False,
        "mode": "excerpt",
        "fallback_reason": fallback_reason,
        "actions": action_buttons(source_action_ids(articles)[:1], role, language),
    }
