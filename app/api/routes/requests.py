from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.core.permissions import (
    ensure_can_view_profile,
    get_profile,
)
from app.core.security import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext
from app.schemas.digital_hr import RequestCreate, RequestReview
from app.services.notifications import create_notification, notify_hr
from app.services.calendar_export import CalendarExportUnavailable, leave_calendar

router = APIRouter(prefix="/requests", tags=["HR requests"])


def _get_request(request_id: str) -> dict:
    response = (
        get_supabase_client()
        .table("hr_requests")
        .select("*")
        .eq("id", request_id)
        .limit(1)
        .execute()
    )
    requests = response.data or []
    if not requests:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return requests[0]


@router.get("")
def list_requests(
    employee_id: str | None = Query(default=None),
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    client = get_supabase_client()
    query = client.table("hr_requests").select("*").order("created_at", desc=True)

    if employee_id:
        profile = get_profile(employee_id)
        ensure_can_view_profile(actor, profile)
        query = query.eq("employee_id", employee_id)
    elif actor.role == "worker":
        query = query.eq("employee_id", actor.id)
    elif actor.role in ("manager", "director"):
        direct_reports = (
            client.table("employee_profiles")
            .select("id")
            .eq("manager_id", actor.id)
            .execute()
            .data
            or []
        )
        employee_ids = [actor.id, *(str(profile["id"]) for profile in direct_reports)]
        query = query.in_("employee_id", employee_ids)

    response = query.execute()
    return response.data or []


@router.post("", status_code=status.HTTP_201_CREATED)
def create_request(
    payload: RequestCreate,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    result = (
        get_supabase_client()
        .table("hr_requests")
        .insert({"employee_id": actor.id, **payload.model_dump(mode="json")})
        .execute()
    )
    created = (result.data or [None])[0]
    if created is None:
        raise HTTPException(status_code=500, detail="Request could not be created")

    employee = get_profile(actor.id)
    title = "Новая заявка сотрудника"
    body = f"{employee['full_name']} создал(а) заявку: {payload.request_type}."
    if employee.get("manager_id"):
        create_notification(
            str(employee["manager_id"]), title, body, "request_created", str(created["id"])
        )
    else:
        notify_hr(title, body, "request_created", str(created["id"]))
    return created


@router.get("/{request_id}")
def request_details(
    request_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    request = _get_request(request_id)
    profile = get_profile(str(request["employee_id"]))
    ensure_can_view_profile(actor, profile)
    return request


@router.get("/{request_id}/calendar.ics", response_class=Response, responses={
    200: {"description": "iCalendar file; import manually into Google Calendar",
          "content": {"text/calendar": {"schema": {"type": "string", "format": "binary"}}}},
    401: {"description": "Authentication required"},
    403: {"description": "No access to this employee"},
    404: {"description": "Request not found"},
    409: {"description": "Not an approved leave or invalid dates"},
    503: {"description": "Request storage unavailable"},
})
def export_request_calendar(
    request_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> Response:
    """Uses the same employee visibility rules as request_details; no writes."""
    try:
        request = _get_request(str(request_id))
        profile = get_profile(str(request["employee_id"]))
        ensure_can_view_profile(actor, profile)
        content = leave_calendar(request)
    except CalendarExportUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, HTTPError, APIError) as exc:
        raise HTTPException(status_code=503, detail="Request storage is temporarily unavailable") from exc
    return Response(content, media_type="text/calendar; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="leave-{request_id}.ics"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.patch("/{request_id}/review")
def review_request(
    request_id: str,
    payload: RequestReview,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    if actor.role not in ("manager", "director", "hr_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer role required")

    request = _get_request(request_id)
    employee = get_profile(str(request["employee_id"]))
    now = datetime.now(UTC).isoformat()
    if actor.role == "manager":
        if employee.get("manager_id") != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot review this employee's request")
        if request["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only requests awaiting manager review can be reviewed",
            )
        next_status = "rejected"
        if payload.status == "approved":
            next_status = "pending_hr"
        update = {
            "status": next_status,
            "manager_reviewed_by": actor.id,
            "manager_reviewed_at": now,
            "manager_reviewer_comment": payload.reviewer_comment,
        }
        if next_status == "rejected":
            update.update(
                {
                    "reviewer_comment": payload.reviewer_comment,
                    "reviewed_by": actor.id,
                    "reviewed_at": now,
                }
            )
        expected_status = "pending"
    elif actor.role == "director":
        if employee.get("manager_id") != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot review this employee's request")
        if request["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only direct reports' requests awaiting review can be reviewed",
            )
        expected_status = "pending"
        next_status = "pending_hr" if payload.status == "approved" else "rejected"
        update = {
            "status": next_status,
            "director_reviewed_by": actor.id,
            "director_reviewed_at": now,
            "director_reviewer_comment": payload.reviewer_comment,
        }
        if next_status == "rejected":
            update.update(
                {
                    "reviewer_comment": payload.reviewer_comment,
                    "reviewed_by": actor.id,
                    "reviewed_at": now,
                }
            )
    else:
        if request["status"] == "pending_hr":
            expected_status = "pending_hr"
        elif request["status"] == "pending" and not employee.get("manager_id"):
            # Requests without a reporting line are routed directly to HR.
            expected_status = "pending"
        elif request["status"] == "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
            detail="Manager review is required before HR review",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only requests awaiting HR review can be reviewed",
            )
        next_status = payload.status
        update = {
            "status": next_status,
            "reviewer_comment": payload.reviewer_comment,
            "reviewed_by": actor.id,
            "reviewed_at": now,
            "hr_reviewed_by": actor.id,
            "hr_reviewed_at": now,
            "hr_reviewer_comment": payload.reviewer_comment,
        }

    result = (
        get_supabase_client()
        .table("hr_requests")
        .update(update)
        .eq("id", request_id)
        .eq("status", expected_status)
        .execute()
    )
    updated = (result.data or [None])[0]
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request was already reviewed")

    if actor.role in ("manager", "director") and next_status == "pending_hr":
        create_notification(
            str(employee["id"]),
            "Заявка передана в HR",
            "Заявка передана в HR для окончательного рассмотрения.",
            "request_pending_hr",
            request_id,
        )
        notify_hr(
            "Заявка ожидает рассмотрения HR",
            f"Заявка сотрудника {employee['full_name']} прошла согласование руководства; требуется решение HR.",
            "request_pending_hr",
            request_id,
        )
    else:
        create_notification(
            str(employee["id"]),
            "Статус заявки изменён",
            f"Ваша заявка получила статус: {next_status}.",
            "request_status_changed",
            request_id,
        )
    return updated
