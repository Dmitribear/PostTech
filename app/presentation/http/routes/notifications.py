from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.dto.digital_hr import NotificationResponse
from app.application.use_cases import notifications as use_cases
from app.domain.models import UserContext
from app.presentation.http.responses import render_result
from app.presentation.http.security import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    request_id: UUID | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    return render_result(
        use_cases.list_notifications(
            request_id=request_id,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
            actor=actor,
        )
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: UUID, actor: UserContext = Depends(get_current_user)
) -> dict:
    return render_result(
        use_cases.mark_notification_read(notification_id=notification_id, actor=actor)
    )
