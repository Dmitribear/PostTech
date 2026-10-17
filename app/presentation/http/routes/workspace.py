from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.use_cases import workspace as use_cases
from app.application.use_cases.workspace import (
    CourseEdit,
    Deadline,
    DelegationInput,
    TicketAnswer,
    TicketInput,
)
from app.domain.models import UserContext
from app.presentation.http.responses import render_result
from app.presentation.http.security import get_current_user

router = APIRouter(prefix="/workspace", tags=["Workspace"])


@router.get("/delegations")
def delegations(actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.delegations(actor=actor))


@router.post("/delegations", status_code=201)
def create_delegation(
    payload: DelegationInput, actor: UserContext = Depends(get_current_user)
):
    return render_result(use_cases.create_delegation(payload=payload, actor=actor))


@router.delete("/delegations/{delegation_id}")
def revoke_delegation(
    delegation_id: UUID, actor: UserContext = Depends(get_current_user)
):
    return render_result(
        use_cases.revoke_delegation(delegation_id=delegation_id, actor=actor)
    )


@router.get("/courses")
def editor_courses(actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.editor_courses(actor=actor))


@router.post("/courses")
def edit_course(payload: CourseEdit, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.edit_course(payload=payload, actor=actor))


@router.patch("/assignments/{assignment_id}/deadline")
def deadline(
    assignment_id: UUID,
    payload: Deadline,
    actor: UserContext = Depends(get_current_user),
):
    return render_result(
        use_cases.deadline(assignment_id=assignment_id, payload=payload, actor=actor)
    )


@router.get("/tickets")
def tickets(
    actor: UserContext = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Literal["open", "resolved"] | None = None,
    search: str = Query("", max_length=120),
):
    return render_result(
        use_cases.tickets(
            actor=actor, limit=limit, offset=offset, status=status, search=search
        )
    )


@router.get("/tickets/{ticket_id}")
def ticket(ticket_id: UUID, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.ticket(ticket_id=ticket_id, actor=actor))


@router.post("/tickets", status_code=201)
def create_ticket(payload: TicketInput, actor: UserContext = Depends(get_current_user)):
    return render_result(use_cases.create_ticket(payload=payload, actor=actor))


@router.post("/tickets/{ticket_id}/answer")
def answer_ticket(
    ticket_id: UUID,
    payload: TicketAnswer,
    actor: UserContext = Depends(get_current_user),
):
    return render_result(
        use_cases.answer_ticket(ticket_id=ticket_id, payload=payload, actor=actor)
    )
