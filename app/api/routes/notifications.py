from app.core.locale import notification_content
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext
from app.schemas.digital_hr import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    request_id: UUID | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    query = (
        get_supabase_client()
        .table("notifications")
        .select("*")
        .eq("employee_id", actor.id)
    )
    if request_id is not None:
        query = query.eq("request_id", str(request_id))
    if unread_only:
        query = query.is_("read_at", "null")
    response = query.order("created_at", desc=True).order("id", desc=True).range(offset, offset + limit - 1).execute()
    return [notification_content(n) for n in response.data or []]


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    result = (
        get_supabase_client()
        .table("notifications")
        .update({"read_at": datetime.now(UTC).isoformat()})
        .eq("id", str(notification_id))
        .eq("employee_id", actor.id)
        .is_("read_at", "null")
        .execute()
    )
    notification = (result.data or [None])[0]
    if notification is None:
        # A retry returns the first read timestamp; the conditional UPDATE also
        # prevents concurrent clicks from rewriting it. Ownership applies here too.
        result = (
            get_supabase_client().table("notifications").select("*")
            .eq("id", str(notification_id)).eq("employee_id", actor.id).limit(1).execute()
        )
        notification = (result.data or [None])[0]
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification_content(notification)
