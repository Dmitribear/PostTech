from datetime import UTC, datetime
from uuid import UUID

from app.application.dependencies import get_data_gateway
from app.domain.errors import ApplicationError
from app.domain.localization import notification_content
from app.domain.models import UserContext


def list_notifications(
    request_id: UUID | None = None,
    unread_only: bool = False,
    limit: int = 100,
    offset: int = 0,
    actor: UserContext = None,
) -> list[dict]:
    query = (
        get_data_gateway()
        .table("notifications")
        .select("*")
        .eq("employee_id", actor.id)
    )
    if request_id is not None:
        query = query.eq("request_id", str(request_id))
    if unread_only:
        query = query.is_("read_at", "null")
    response = (
        query.order("created_at", desc=True)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return [notification_content(n) for n in response.data or []]


def mark_notification_read(notification_id: UUID, actor: UserContext = None) -> dict:
    result = (
        get_data_gateway()
        .table("notifications")
        .update({"read_at": datetime.now(UTC).isoformat()})
        .eq("id", str(notification_id))
        .eq("employee_id", actor.id)
        .is_("read_at", "null")
        .execute()
    )
    notification = (result.data or [None])[0]
    if notification is None:
        result = (
            get_data_gateway()
            .table("notifications")
            .select("*")
            .eq("id", str(notification_id))
            .eq("employee_id", actor.id)
            .limit(1)
            .execute()
        )
        notification = (result.data or [None])[0]
    if notification is None:
        raise ApplicationError(status_code=404, detail="Notification not found")
    return notification_content(notification)
