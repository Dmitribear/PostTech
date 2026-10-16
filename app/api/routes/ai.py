from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.schemas.digital_hr import JanaQuestion
from app.services.jana import answer_question

router = APIRouter(prefix="/ai", tags=["AI Jana"])


@router.post("/ask")
def ask_jana(
    payload: JanaQuestion,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Answer only from the prepared HR knowledge base and return citations."""
    return answer_question(payload.question)
