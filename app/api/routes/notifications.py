from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext
from app.services.notifications import list_employee_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    return list_employee_notifications(get_supabase_client(), actor.id)


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    result = (
        get_supabase_client()
        .table("notifications")
        .update({"read_at": datetime.now(UTC).isoformat()})
        .eq("id", notification_id)
        .eq("employee_id", actor.id)
        .execute()
    )
    notification = (result.data or [None])[0]
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification
