from uuid import UUID

from fastapi import APIRouter, Depends

from app.application.dto.digital_hr import JanaQuestion
from app.domain.localization import locale
from app.domain.models import UserContext
from app.infrastructure.ai.jana import answer_question, get_source
from app.presentation.http.security import get_current_user

router = APIRouter(prefix="/ai", tags=["AI Jana"])


@router.post("/ask")
def ask_jana(
    payload: JanaQuestion,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    question = payload.question
    from app.application.use_cases.workflow_summary import (
        SUMMARY_PROMPTS,
        summary_answer,
    )

    if question.strip().lower().rstrip(".") in SUMMARY_PROMPTS:
        return summary_answer(actor)
    if locale.get() == "kk":
        # Canonical UI prompts; free-form questions still pass the normal guards.
        question = {
            "Демалысты қалай рәсімдеуге болады?": "Как оформить отпуск?",
            "Авансты қалай сұрауға болады?": "Как запросить аванс?",
            "Өтінім мәртебесін қайдан көруге болады?": "Где посмотреть статус заявки?",
            "Менің кадрлық деректерімді кім көреді?": "Кто видит мои кадровые данные?",
        }.get(question, question)
    result = answer_question(question, language=locale.get())
    if locale.get() == "kk":
        if not result["grounded"]:
            result["answer"] = (
                "Jana бұл сұраққа дереккөздермен расталған жауап бере алмайды. Сұрақты HR-ға жіберуге болады. Жеке деректерді профильден қараңыз."
            )
        elif result.get("mode") != "generated":
            result["answer"] = (
                "Дереккөздің түпнұсқасы орыс тілінде. Төменде расталған үзінді берілген:\n\n"
                + result["answer"]
            )
    return result


@router.get("/sources/{source_id}")
def knowledge_source(
    source_id: UUID,
    version: str | None = None,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    return (
        get_source(source_id, version) if version is not None else get_source(source_id)
    )
