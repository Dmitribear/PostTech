"""HR administration and explicitly consented employee support."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator, ValidationError

from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.services.academy import _client, _execute, _all_rows, _command

router = APIRouter(prefix="/workspace", tags=["Workspace"])


def hr(actor: UserContext):
    if actor.role != "hr_admin":
        raise HTTPException(403, "HR role required")


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DelegationInput(Payload):
    id: UUID
    manager_id: UUID
    deputy_id: UUID
    starts_on: date
    ends_on: date
    reason: str = Field(default="", max_length=1000)


@router.get("/delegations")
def delegations(actor: UserContext = Depends(get_current_user)):
    def query():
        q = _client().table("approval_delegations").select("*")
        if actor.role != "hr_admin":
            q = q.or_(f"manager_id.eq.{actor.id},deputy_id.eq.{actor.id}")
        return q.order("created_at", desc=True).order("id")
    return _all_rows(query)


@router.post("/delegations", status_code=201)
def create_delegation(payload: DelegationInput, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _command("manage_approval_delegation", {"p_actor_id": actor.id, **{
        f"p_{k}": v for k, v in payload.model_dump(mode="json").items()}})


@router.delete("/delegations/{delegation_id}")
def revoke_delegation(delegation_id: UUID, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _command("manage_approval_delegation", dict(p_actor_id=actor.id, p_id=str(delegation_id),
        p_manager_id=None, p_deputy_id=None, p_starts_on=None, p_ends_on=None, p_reason="", p_revoke=True))


class EditorQuestion(Payload):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    prompt: str = Field(min_length=3, max_length=2000)
    options: list[str] = Field(min_length=2, max_length=10)
    answer_index: int = Field(ge=0, le=9, strict=True)

    @model_validator(mode="after")
    def valid_options(self):
        if self.answer_index >= len(self.options) or any(not x.strip() or len(x)>1000 for x in self.options):
            raise ValueError("Every option needs text and the answer must reference an existing option")
        if len(set(self.options)) != len(self.options):
            raise ValueError("Quiz options must be distinct")
        return self


class CourseTranslation(Payload):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(max_length=2000)
    material_markdown: str = Field(min_length=3, max_length=60000)
    quiz: list[EditorQuestion] = Field(min_length=1, max_length=50)


class CourseData(CourseTranslation):
    family_id: UUID | None = None
    duration_minutes: int = Field(ge=1, le=1440)
    passing_score: int = Field(ge=1, le=100)
    category: str = Field(min_length=1, max_length=100)
    audience: str = Field(min_length=1, max_length=100)
    translations: dict[Literal["kk"], CourseTranslation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def matching_quiz(self):
        if len({q.id for q in self.quiz}) != len(self.quiz):
            raise ValueError("Question IDs must be unique")
        for translated in self.translations.values():
            if [(q.id,len(q.options),q.answer_index) for q in translated.quiz] != [(q.id,len(q.options),q.answer_index) for q in self.quiz]:
                raise ValueError("Translations must preserve question IDs, option order and correct answers")
        return self


class CourseEdit(Payload):
    id: UUID
    action: Literal["create", "save", "publish", "archive"]
    revision: int = Field(default=0, ge=0)
    data: CourseData | None = None


@router.get("/courses")
def editor_courses(actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _all_rows(lambda: _client().table("courses").select("*").order("created_at", desc=True).order("id"))


@router.post("/courses")
def edit_course(payload: CourseEdit, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    if payload.action in ("create", "save") and payload.data is None:
        raise HTTPException(422, "Course content required")
    if payload.action == "publish":
        rows = _execute(_client().table("courses").select("*").eq("id",str(payload.id)).limit(1)) or []
        if not rows:
            raise HTTPException(404,"Course not found")
        row = rows[0]
        try:
            CourseData.model_validate({k:row[k] for k in CourseData.model_fields if k in row})
        except ValidationError as exc:
            raise HTTPException(422,"Course content or translation is invalid") from exc
    return _command("edit_academy_course", dict(p_actor_id=actor.id,p_id=str(payload.id),p_action=payload.action,
        p_revision=payload.revision,p_data=payload.data.model_dump(mode="json") if payload.data else {}))


class Deadline(Payload):
    due_on: date | None


@router.patch("/assignments/{assignment_id}/deadline")
def deadline(assignment_id: UUID, payload: Deadline, actor: UserContext = Depends(get_current_user)):
    return _command("set_course_deadline",dict(p_actor_id=actor.id,p_assignment_id=str(assignment_id),
        p_due_on=payload.due_on.isoformat() if payload.due_on else None))


class TicketInput(Payload):
    id: UUID
    question: str = Field(min_length=3,max_length=2000)
    context: str = Field(default="",max_length=6000)
    consent: Literal[True]


class TicketAnswer(Payload):
    answer: str = Field(min_length=3,max_length=6000)


@router.get("/tickets")
def tickets(actor: UserContext = Depends(get_current_user), limit: int = Query(50,ge=1,le=100), offset:int=Query(0,ge=0)):
    q = _client().table("hr_tickets").select("*")
    if actor.role != "hr_admin":
        q = q.eq("employee_id",actor.id)
    return _execute(q.order("created_at",desc=True).order("id").range(offset,offset+limit-1)) or []


@router.get("/tickets/{ticket_id}")
def ticket(ticket_id: UUID, actor: UserContext = Depends(get_current_user)):
    q = _client().table("hr_tickets").select("*").eq("id",str(ticket_id))
    if actor.role != "hr_admin":
        q=q.eq("employee_id",actor.id)
    rows=_execute(q.limit(1)) or []
    if not rows: raise HTTPException(404,"Ticket not found")
    return rows[0]


@router.post("/tickets",status_code=201)
def create_ticket(payload:TicketInput,actor:UserContext=Depends(get_current_user)):
    return _command("create_hr_ticket",dict(p_actor_id=actor.id,**{f"p_{k}":v for k,v in payload.model_dump(mode="json").items()}))


@router.post("/tickets/{ticket_id}/answer")
def answer_ticket(ticket_id:UUID,payload:TicketAnswer,actor:UserContext=Depends(get_current_user)):
    hr(actor)
    return _command("answer_hr_ticket",dict(p_actor_id=actor.id,p_id=str(ticket_id),p_answer=payload.answer))
