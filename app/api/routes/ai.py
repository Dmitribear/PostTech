from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.schemas.digital_hr import JanaQuestion
from app.services.jana import answer_question, get_source_article

router = APIRouter(prefix="/ai", tags=["AI Jana"])


@router.post("/ask")
def ask_jana(
    payload: JanaQuestion,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Answer only from the prepared HR knowledge base and return citations."""
    return answer_question(payload.question)


@router.get("/sources/{article_id}")
def read_jana_source(
    article_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Read a published, company-wide FAQ source as an authenticated employee."""
    article = get_source_article(str(article_id))
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return article
