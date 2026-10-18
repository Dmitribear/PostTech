"""HR administration and explicitly consented employee support."""

from datetime import date
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.application.use_cases.academy import (
    data_gateway,
    execute_command,
    execute_query,
    read_all_rows,
)
from app.domain.errors import ApplicationError
from app.domain.models import UserContext


def hr(actor: UserContext):
    if actor.role != "hr_admin":
        raise ApplicationError(403, "HR role required")


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DelegationInput(Payload):
    id: UUID
    manager_id: UUID
    deputy_id: UUID
    starts_on: date
    ends_on: date
    reason: str = Field(default="", max_length=1000)


def delegations(actor: UserContext = None):

    def query():
        q = data_gateway().table("approval_delegations").select("*")
        if actor.role != "hr_admin":
            q = q.or_(f"manager_id.eq.{actor.id},deputy_id.eq.{actor.id}")
        return q.order("created_at", desc=True).order("id")

    return read_all_rows(query)


def create_delegation(payload: DelegationInput, actor: UserContext = None):
    hr(actor)
    return execute_command(
        "manage_approval_delegation",
        {
            "p_actor_id": actor.id,
            **{f"p_{k}": v for k, v in payload.model_dump(mode="json").items()},
        },
    )


def revoke_delegation(delegation_id: UUID, actor: UserContext = None):
    hr(actor)
    return execute_command(
        "manage_approval_delegation",
        dict(
            p_actor_id=actor.id,
            p_id=str(delegation_id),
            p_manager_id=None,
            p_deputy_id=None,
            p_starts_on=None,
            p_ends_on=None,
            p_reason="",
            p_revoke=True,
        ),
    )


class EditorQuestion(Payload):
    id: str = Field(min_length=1, max_length=80, pattern="^[a-zA-Z0-9_-]+$")
    prompt: str = Field(min_length=3, max_length=2000)
    options: list[str] = Field(min_length=2, max_length=10)
    answer_index: int = Field(ge=0, le=9, strict=True)

    @model_validator(mode="after")
    def valid_options(self):
        if self.answer_index >= len(self.options) or any(
            (not x.strip() or len(x) > 1000 for x in self.options)
        ):
            raise ValueError(
                "Every option needs text and the answer must reference an existing option"
            )
        if len(set(self.options)) != len(self.options):
            raise ValueError("Quiz options must be distinct")
        return self


class Lesson(Payload):
    id: str = Field(min_length=1, max_length=80, pattern="^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=3, max_length=200)
    material_markdown: str = Field(min_length=3, max_length=60000)


class CourseTranslation(Payload):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(max_length=2000)
    material_markdown: str = Field(default="", max_length=60000)
    quiz: list[EditorQuestion] = Field(default_factory=list, max_length=50)
    lessons: list[Lesson] = Field(default_factory=list, max_length=50)


class CourseData(CourseTranslation):
    course_type: Literal["internal", "external"] = "internal"
    provider: str = Field(default="", max_length=160)
    external_url: str | None = Field(default=None, max_length=2000)
    family_id: UUID | None = None
    duration_minutes: int = Field(ge=0, le=525600)
    passing_score: int = Field(ge=1, le=100)
    category: str = Field(min_length=1, max_length=100)
    audience: str = Field(min_length=1, max_length=100)
    translations: dict[Literal["kk"], CourseTranslation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def matching_quiz(self):
        if self.course_type == "external":
            link = urlsplit(self.external_url or "")
            if (
                link.scheme != "https"
                or not link.hostname
                or link.username
                or link.password
                or not self.provider
            ):
                raise ValueError(
                    "External courses need a provider and an HTTPS URL without credentials"
                )
            if self.lessons or self.quiz:
                raise ValueError(
                    "External courses track progress on the provider platform"
                )
        elif (
            len(self.material_markdown.strip()) < 3
            or not self.quiz
            or self.duration_minutes < 1
        ):
            raise ValueError("Internal courses need material and a quiz")
        if len({lesson.id for lesson in self.lessons}) != len(self.lessons):
            raise ValueError("Lesson IDs must be unique")
        if len({q.id for q in self.quiz}) != len(self.quiz):
            raise ValueError("Question IDs must be unique")
        for translated in self.translations.values():
            if self.course_type == "internal" and (
                len(translated.material_markdown.strip()) < 3 or not translated.quiz
            ):
                raise ValueError(
                    "Internal course translations need material and a quiz"
                )
            if [x.id for x in translated.lessons] != [x.id for x in self.lessons]:
                raise ValueError("Translations must preserve lesson IDs and order")
            if [(q.id, len(q.options), q.answer_index) for q in translated.quiz] != [
                (q.id, len(q.options), q.answer_index) for q in self.quiz
            ]:
                raise ValueError(
                    "Translations must preserve question IDs, option order and correct answers"
                )
        return self


class CourseEdit(Payload):
    id: UUID
    action: Literal["create", "save", "publish", "archive"]
    revision: int = Field(default=0, ge=0)
    data: CourseData | None = None


def editor_courses(actor: UserContext = None):
    hr(actor)
    rows = read_all_rows(
        lambda: (
            data_gateway()
            .table("courses")
            .select("*")
            .order("created_at", desc=True)
            .order("id")
        )
    )

    return [row for row in rows if not row.get("owner_employee_id")]


def edit_course(payload: CourseEdit, actor: UserContext = None):
    hr(actor)
    ids = [str(payload.id)]
    if payload.data and payload.data.family_id:
        ids.append(str(payload.data.family_id))
    existing = (
        execute_query(
            data_gateway().table("courses").select("owner_employee_id").in_("id", ids)
        )
        or []
    )
    if any(row.get("owner_employee_id") for row in existing):
        raise ApplicationError(403, "Personal courses are managed in employee learning")
    if payload.action in ("create", "save") and payload.data is None:
        raise ApplicationError(422, "Course content required")
    if payload.action == "publish":
        rows = (
            execute_query(
                data_gateway()
                .table("courses")
                .select("*")
                .eq("id", str(payload.id))
                .limit(1)
            )
            or []
        )
        if not rows:
            raise ApplicationError(404, "Course not found")
        row = rows[0]
        try:
            CourseData.model_validate(
                {k: row[k] for k in CourseData.model_fields if k in row}
            )
        except ValidationError as exc:
            raise ApplicationError(
                422, "Course content or translation is invalid"
            ) from exc
    return execute_command(
        "edit_academy_course",
        dict(
            p_actor_id=actor.id,
            p_id=str(payload.id),
            p_action=payload.action,
            p_revision=payload.revision,
            p_data=payload.data.model_dump(mode="json") if payload.data else {},
        ),
    )


class Deadline(Payload):
    due_on: date | None


def deadline(assignment_id: UUID, payload: Deadline, actor: UserContext = None):
    return execute_command(
        "set_course_deadline",
        dict(
            p_actor_id=actor.id,
            p_assignment_id=str(assignment_id),
            p_due_on=payload.due_on.isoformat() if payload.due_on else None,
        ),
    )


class TicketInput(Payload):
    id: UUID
    question: str = Field(min_length=3, max_length=2000)
    context: str = Field(default="", max_length=6000)
    consent: Literal[True]


class TicketAnswer(Payload):
    answer: str = Field(min_length=3, max_length=6000)


def tickets(
    actor: UserContext = None,
    limit: int = 50,
    offset: int = 0,
    status: Literal["open", "resolved"] | None = None,
    search: str = "",
):
    q = data_gateway().table("hr_tickets").select("*")
    if actor.role != "hr_admin":
        q = q.eq("employee_id", actor.id)
    if status:
        q = q.eq("status", status)
    if search.strip():
        term = (
            search.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("*", "\\*")
        )
        q = q.ilike("question", f"%{term}%")
    return (
        execute_query(
            q.order("created_at", desc=True)
            .order("id")
            .range(offset, offset + limit - 1)
        )
        or []
    )


def ticket(ticket_id: UUID, actor: UserContext = None):
    q = data_gateway().table("hr_tickets").select("*").eq("id", str(ticket_id))
    if actor.role != "hr_admin":
        q = q.eq("employee_id", actor.id)
    rows = execute_query(q.limit(1)) or []
    if not rows:
        raise ApplicationError(404, "Ticket not found")
    return rows[0]


def create_ticket(payload: TicketInput, actor: UserContext = None):
    return execute_command(
        "create_hr_ticket",
        dict(
            p_actor_id=actor.id,
            **{f"p_{k}": v for k, v in payload.model_dump(mode="json").items()},
        ),
    )


def answer_ticket(ticket_id: UUID, payload: TicketAnswer, actor: UserContext = None):
    hr(actor)
    return execute_command(
        "answer_hr_ticket",
        dict(p_actor_id=actor.id, p_id=str(ticket_id), p_answer=payload.answer),
    )
