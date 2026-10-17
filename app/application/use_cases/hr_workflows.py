from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.application.ports import FileResult as Response
from app.application.use_cases import employee_import
from app.application.use_cases.academy import (
    data_gateway,
    execute_command,
    execute_query,
    read_all_rows,
)
from app.application.use_cases.requests import get_request
from app.application.use_cases.workflow_summary import operational_summary
from app.application.use_cases.workspace import Payload, hr
from app.domain.errors import ApplicationError
from app.domain.models import UserContext


def fulfillment_queue(
    offset: int = 0,
    state: Literal["awaiting_hr", "processing", "completed"] = "awaiting_hr",
    actor: UserContext = None,
):
    hr(actor)
    return (
        execute_query(
            data_gateway()
            .table("request_fulfillment")
            .select(
                "*,hr_requests!inner(employee_id,request_type,start_date,end_date,amount,employee_profiles!hr_requests_employee_id_fkey(full_name))"
            )
            .eq("status", state)
            .order("updated_at")
            .order("request_id")
            .range(offset, offset + 19)
        )
        or []
    )


def fulfillment_detail(request_id: UUID, actor: UserContext = None):
    get_request(actor, request_id)
    records = (
        execute_query(
            data_gateway()
            .table("request_fulfillment")
            .select("*")
            .eq("request_id", str(request_id))
            .limit(1)
        )
        or []
    )
    if not records:
        return None
    events = read_all_rows(
        lambda: (
            data_gateway()
            .table("fulfillment_events")
            .select("id,action,detail,created_at")
            .eq("request_id", str(request_id))
            .order("created_at")
            .order("id")
        )
    )
    deliveries = (
        execute_query(
            data_gateway()
            .table("integration_outbox")
            .select("destination,status,attempts,delivered_at")
            .eq("aggregate_id", str(request_id))
        )
        or []
    )
    from app.application.integration_delivery import configured_destinations

    return {
        **records[0],
        "events": events,
        "deliveries": deliveries,
        "can_send": all(configured_destinations().values()),
    }


class FulfillInput(Payload):
    action: Literal["start", "complete"]
    reference: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)


def fulfill(request_id: UUID, payload: FulfillInput, actor: UserContext = None):
    hr(actor)
    if payload.action == "start":
        from app.application.integration_delivery import configuration

        if not all((configuration(d) for d in ("1c", "documentolog"))):
            raise ApplicationError(
                409, "Подключите оба приёмника или оформите документ вручную"
            )
    return execute_command(
        "fulfill_hr_request",
        {
            "p_actor_id": actor.id,
            "p_request_id": str(request_id),
            "p_action": payload.action,
            "p_reference": payload.reference,
            "p_note": payload.note,
        },
    )


def import_template(actor: UserContext = None):
    hr(actor)
    return Response(
        "\ufeff" + ",".join(employee_import.HEADERS) + "\r\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="employees.csv"'},
    )


class ImportInput(Payload):
    filename: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2800000)


def import_preview(payload: ImportInput, actor: UserContext = None):
    hr(actor)
    return employee_import.preview(actor, payload.filename, payload.content)


def import_apply(batch_id: UUID, actor: UserContext = None):
    hr(actor)
    return employee_import.apply(actor, batch_id)


class TrackStep(Payload):
    course_id: UUID
    days_to_complete: int = Field(ge=1, le=365)


class TrackInput(Payload):
    id: UUID
    title: str = Field(min_length=3, max_length=160)
    steps: list[TrackStep] = Field(min_length=1, max_length=30)
    auto_role: Literal["worker", "manager", "hr_admin"] | None = None


def tracks(actor: UserContext = None):
    hr(actor)
    return read_all_rows(
        lambda: (
            data_gateway()
            .table("learning_tracks")
            .select("*,learning_track_steps(*,courses(title))")
            .eq("active", True)
            .order("created_at")
            .order("id")
        )
    )


def create_track(payload: TrackInput, actor: UserContext = None):
    hr(actor)
    return execute_command(
        "create_learning_track",
        {
            "p_actor_id": actor.id,
            **{f"p_{k}": v for k, v in payload.model_dump(mode="json").items()},
        },
    )


def archive_track(track_id: UUID, actor: UserContext = None):
    hr(actor)
    return execute_query(
        data_gateway()
        .table("learning_tracks")
        .update({"active": False, "auto_role": None})
        .eq("id", str(track_id))
    )


class EnrollmentInput(Payload):
    employee_id: UUID


def enroll(track_id: UUID, payload: EnrollmentInput, actor: UserContext = None):
    hr(actor)
    return execute_command(
        "enroll_learning_track",
        dict(
            p_actor_id=actor.id,
            p_track_id=str(track_id),
            p_employee_id=str(payload.employee_id),
        ),
    )


def my_tracks(employee_id: UUID | None = None, actor: UserContext = None):
    employee = str(employee_id or actor.id)
    if employee != actor.id and actor.role != "hr_admin":
        if actor.role not in ("manager", "director") or not execute_query(
            data_gateway()
            .table("employee_profiles")
            .select("id")
            .eq("id", employee)
            .eq("manager_id", actor.id)
            .limit(1)
        ):
            raise ApplicationError(403, "Access to this employee is forbidden")
    execute_query(
        data_gateway().rpc("advance_learning_tracks", {"p_employee_id": employee})
    )
    enrolled = read_all_rows(
        lambda: (
            data_gateway()
            .table("learning_enrollments")
            .select(
                "*,learning_tracks(title,learning_track_steps(position,course_id,days_to_complete,courses(title)))"
            )
            .eq("employee_id", employee)
            .order("enrolled_at")
            .order("id")
        )
    )
    assigned = read_all_rows(
        lambda: (
            data_gateway()
            .table("course_assignments")
            .select("course_id,status,due_on,progress_percent")
            .eq("employee_id", employee)
            .order("id")
        )
    )
    by_course = {a["course_id"]: a for a in assigned}
    for row in enrolled:
        steps = sorted(
            row["learning_tracks"].pop("learning_track_steps"),
            key=lambda s: s["position"],
        )
        for step in steps:
            step["assignment"] = by_course.get(step["course_id"])
        row["steps"] = steps
    return enrolled


def summary(actor: UserContext = None):
    return operational_summary(actor)


class PolicyInput(Payload):
    enabled: bool
    remind_hours: int = Field(ge=1, le=720)
    escalate_hours: int = Field(ge=2, le=1440)
    course_notice_days: int = Field(ge=0, le=30)

    @model_validator(mode="after")
    def order(self):
        if self.escalate_hours <= self.remind_hours:
            raise ValueError("Эскалация должна быть позже напоминания")
        return self


def policy(actor: UserContext = None):
    hr(actor)
    return execute_query(
        data_gateway().table("workflow_policy").select("*").eq("id", True)
    )[0]


def save_policy(payload: PolicyInput, actor: UserContext = None):
    from datetime import UTC, datetime

    hr(actor)
    return execute_query(
        data_gateway()
        .table("workflow_policy")
        .update(
            {
                **payload.model_dump(),
                "updated_by": actor.id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", True)
    )[0]


def run_policy(actor: UserContext = None):
    hr(actor)
    return execute_command("run_workflow_reminders", {})
