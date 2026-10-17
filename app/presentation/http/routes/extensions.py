from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.use_cases import extensions as use_cases
from app.application.use_cases.extensions import (
    BalanceInput,
    KnowledgeEdit,
)
from app.domain.models import UserContext
from app.presentation.http.responses import render_result
from app.presentation.http.security import get_current_user

router = APIRouter(prefix="/workspace", tags=["Operations"])


@router.get("/leave-balance")
def leave_balance(
    employee_id: UUID | None = None,
    request_id: UUID | None = None,
    actor: UserContext = Depends(get_current_user),
):
    return render_result(
        use_cases.leave_balance(
            employee_id=employee_id, request_id=request_id, actor=actor
        )
    )


@router.post("/leave-balance/reconcile")
def reconcile(payload: BalanceInput, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.reconcile(payload=payload, actor=actor))


@router.get("/knowledge")
def knowledge(
    actor: UserContext = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    return render_result(use_cases.knowledge(actor=actor, offset=offset, limit=limit))


@router.get("/knowledge/{article_id}/history")
def knowledge_history(article_id: UUID, actor: UserContext = Depends(get_current_user)):
    return render_result(
        use_cases.knowledge_history(article_id=article_id, actor=actor)
    )


@router.post("/knowledge")
def edit_knowledge(
    payload: KnowledgeEdit, actor: UserContext = Depends(get_current_user)
):
    return render_result(use_cases.edit_knowledge(payload=payload, actor=actor))


@router.get("/integrations")
def integrations(
    actor: UserContext = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    status: Literal["queued", "sending", "retry", "delivered", "dead"] | None = None,
):
    return render_result(
        use_cases.integrations(actor=actor, offset=offset, status=status)
    )


@router.get("/integrations/{event_id}/attempts")
def attempts(event_id: UUID, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.attempts(event_id=event_id, actor=actor))


@router.post("/integrations/{event_id}/retry")
def retry(event_id: UUID, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.retry(event_id=event_id, actor=actor))


@router.post("/courses/{course_id}/lessons/{lesson_id}/complete")
def complete_lesson(
    course_id: UUID, lesson_id: str, actor: UserContext = Depends(get_current_user)
):
    return render_result(
        use_cases.complete_lesson(course_id=course_id, lesson_id=lesson_id, actor=actor)
    )
