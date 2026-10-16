from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.schemas.digital_hr import JanaQuestion
from app.schemas.jana import JanaAnswer, JanaArticle, JanaError
from app.services.jana import answer_question, get_source_article
from app.services.jana_errors import JanaUnavailable

router = APIRouter(prefix="/ai", tags=["AI Jana"])
ERROR_RESPONSES = {
    401: {"model": JanaError, "description": "Missing or invalid Bearer token"},
    403: {"model": JanaError, "description": "Auth user has no linked HR profile"},
    503: {"model": JanaError, "description": "Knowledge base or AI model unavailable"},
}


@router.post("/ask", response_model=JanaAnswer, responses=ERROR_RESPONSES)
def ask_jana(
    payload: JanaQuestion,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Answer only from the prepared HR knowledge base and return citations."""
    try:
        return answer_question(payload.question)
    except JanaUnavailable as exc:
        raise HTTPException(status_code=503, detail="Jana AI is temporarily unavailable") from exc
    except (RuntimeError, HTTPError, APIError) as exc:
        raise HTTPException(status_code=503, detail="Jana knowledge base is temporarily unavailable") from exc


@router.get(
    "/sources/{article_id}",
    response_model=JanaArticle,
    responses={**ERROR_RESPONSES, 404: {"model": JanaError, "description": "Source missing or inactive"}},
)
def read_jana_source(
    article_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Read a published FAQ source using the same HR authentication as /ask."""
    try:
        article = get_source_article(str(article_id))
    except (RuntimeError, HTTPError, APIError) as exc:
        raise HTTPException(status_code=503, detail="Jana knowledge base is temporarily unavailable") from exc
    if article is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return article
