from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.core.permissions import (
    ensure_can_manage_employee,
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
    elif actor.role == "manager":
        team = (
            client.table("employee_profiles")
            .select("id")
            .eq("manager_id", actor.id)
            .execute()
            .data
            or []
        )
        employee_ids = [actor.id, *(str(profile["id"]) for profile in team)]
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
    if actor.role not in ("manager", "hr_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer role required")

    request = _get_request(request_id)
    employee = ensure_can_manage_employee(actor, str(request["employee_id"]))
    if request["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending requests can be reviewed")

    result = (
        get_supabase_client()
        .table("hr_requests")
        .update(
            {
                "status": payload.status,
                "reviewer_comment": payload.reviewer_comment,
                "reviewed_by": actor.id,
                "reviewed_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
    )
    updated = (result.data or [None])[0]
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request was already reviewed")

    create_notification(
        str(employee["id"]),
        "Статус заявки изменён",
        f"Ваша заявка получила статус: {payload.status}.",
        "request_status_changed",
        request_id,
    )
    return updated
