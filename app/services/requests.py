"""Request reads and transactional commands used by the HTTP API.

The SQL RPCs own each write transaction, including history and notifications.
Only the server's service-role client can execute them; actor IDs always come
from the validated Auth session, never from request bodies.
"""

import logging
from uuid import UUID, uuid4

from fastapi import HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.core.permissions import ensure_can_view_profile
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext
from app.schemas.digital_hr import RequestCreate, RequestReview, RequestStatus, RequestType

logger = logging.getLogger(__name__)

REQUEST_COLUMNS = (
    "id,employee_id,request_type,status,start_date,end_date,amount,comment,"
    "reviewer_comment,reviewed_by,reviewed_at,created_at,updated_at"
)
EVENT_COLUMNS = "id,request_id,actor_id,event_type,from_status,to_status,comment,created_at"


def _client():
    try:
        return get_supabase_client()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="HR database is not configured") from exc


def _execute(query):
    try:
        return query.execute().data
    except APIError as exc:
        if exc.code in {"PT403", "PT404", "PT409", "PT422"}:
            raise HTTPException(status_code=int(exc.code[2:]), detail=exc.message) from exc
        if exc.code in {"PGRST202", "42P01", "42703"}:
            raise HTTPException(
                status_code=503,
                detail="Request workflow is not installed; apply the database migrations",
            ) from exc
        logger.warning("Request database operation failed (code=%s)", exc.code)
        raise HTTPException(status_code=503, detail="HR database operation failed; retry later") from exc
    except HTTPError as exc:
        raise HTTPException(status_code=503, detail="HR database is unavailable; retry later") from exc


def _profile(employee_id: str) -> dict:
    rows = _execute(
        _client().table("employee_profiles").select("id,manager_id").eq("id", employee_id).limit(1)
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Employee not found")
    return rows[0]


def list_requests(
    actor: UserContext,
    *,
    employee_id: UUID | None = None,
    request_status: RequestStatus | None = None,
    request_type: RequestType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    client = _client()
    query = client.table("hr_requests").select(REQUEST_COLUMNS)
    if employee_id is not None:
        ensure_can_view_profile(actor, _profile(str(employee_id)))
        query = query.eq("employee_id", str(employee_id))
    elif actor.role == "worker":
        query = query.eq("employee_id", actor.id)
    elif actor.role == "manager":
        team = _execute(
            client.table("employee_profiles").select("id").eq("manager_id", actor.id)
        ) or []
        query = query.in_("employee_id", [actor.id, *(str(row["id"]) for row in team)])
    if request_status is not None:
        query = query.eq("status", request_status)
    if request_type is not None:
        query = query.eq("request_type", request_type)
    return _execute(
        query.order("created_at", desc=True).order("id", desc=True).range(offset, offset + limit - 1)
    ) or []


def get_request(actor: UserContext, request_id: UUID) -> dict:
    rows = _execute(
        _client().table("hr_requests").select(REQUEST_COLUMNS).eq("id", str(request_id)).limit(1)
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Request not found")
    request = rows[0]
    ensure_can_view_profile(actor, _profile(str(request["employee_id"])))
    return request


def request_history(actor: UserContext, request_id: UUID) -> list[dict]:
    get_request(actor, request_id)
    events = _execute(
        _client().table("request_events").select(EVENT_COLUMNS)
        .eq("request_id", str(request_id)).order("created_at").order("id")
    ) or []
    # Imported/demo requests may have equal creation and decision timestamps.
    return sorted(events, key=lambda event: (
        event["created_at"], event["event_type"] != "created", event["id"],
    ))


def create_request(actor: UserContext, payload: RequestCreate, key: UUID | None) -> dict:
    params = {f"p_{name}": value for name, value in payload.model_dump(mode="json").items()}
    params.update(p_actor_id=actor.id, p_idempotency_key=str(key or uuid4()))
    result = _execute(_client().rpc("create_hr_request", params))
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="Unexpected request workflow response")
    return result


def review_request(actor: UserContext, request_id: UUID, payload: RequestReview) -> dict:
    if actor.role not in ("manager", "hr_admin"):
        raise HTTPException(status_code=403, detail="Reviewer role required")
    result = _execute(_client().rpc("review_hr_request", {
        "p_actor_id": actor.id,
        "p_request_id": str(request_id),
        "p_status": payload.status,
        "p_reviewer_comment": payload.reviewer_comment,
    }))
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="Unexpected request workflow response")
    return result
