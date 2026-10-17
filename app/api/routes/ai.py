from app.core.locale import locale
from fastapi import APIRouter, Depends
from uuid import UUID

from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.schemas.digital_hr import JanaQuestion
from app.services.jana import answer_question, get_source

router = APIRouter(prefix="/ai", tags=["AI Jana"])


@router.post("/ask")
def ask_jana(
    payload: JanaQuestion,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Answer only from the prepared HR knowledge base and return citations."""
    question=payload.question
    if locale.get()=="kk":
        # Canonical UI prompts; free-form questions still pass the normal guards.
        question={"Демалысты қалай рәсімдеуге болады?":"Как оформить отпуск?", "Авансты қалай сұрауға болады?":"Как запросить аванс?",
                  "Өтінім мәртебесін қайдан көруге болады?":"Где посмотреть статус заявки?", "Менің кадрлық деректерімді кім көреді?":"Кто видит мои кадровые данные?"}.get(question,question)
    result=answer_question(question, language=locale.get())
    if locale.get()=="kk":
        if not result["grounded"]:
            result["answer"]="Jana бұл сұраққа дереккөздермен расталған жауап бере алмайды. Сұрақты HR-ға жіберуге болады. Жеке деректерді профильден қараңыз."
        elif result.get("mode") != "generated":
            result["answer"]="Дереккөздің түпнұсқасы орыс тілінде. Төменде расталған үзінді берілген:\n\n"+result["answer"]
    return result


@router.get("/sources/{source_id}")
def knowledge_source(
    source_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Read an active published source with the same authentication as Jana."""
    return get_source(source_id)
