from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, status

from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.schemas.digital_hr import (
    RequestCreate,
    RequestEventResponse,
    RequestResponse,
    RequestReview,
    RequestRoutingResponse,
    RequestStatus,
    RequestType,
)
from app.services import requests as workflow

router = APIRouter(prefix="/requests", tags=["HR requests"])


@router.get("", response_model=list[RequestResponse])
def list_requests(
    employee_id: UUID | None = Query(default=None),
    request_status: RequestStatus | None = Query(default=None, alias="status"),
    request_type: RequestType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scope: Literal["all", "mine", "review"] = Query(default="all"),
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    """Own requests, the manager's team, or all requests for HR; newest first."""
    return workflow.list_requests(
        actor, employee_id=employee_id, request_status=request_status,
        request_type=request_type, limit=limit, offset=offset, scope=scope,
    )


@router.get("/routing", response_model=RequestRoutingResponse)
def request_routing(actor: UserContext = Depends(get_current_user)) -> dict:
    """Preview the caller's own route and the MVP leave policy before submitting."""
    return workflow.request_routing(actor)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RequestResponse)
def create_request(
    payload: RequestCreate,
    idempotency_key: UUID | None = Header(default=None, alias="Idempotency-Key"),
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Create a request, history event and notification atomically.

    Reuse the same UUID Idempotency-Key and body when retrying a submission.
    Identical retries return the same request; a changed body returns 409.
    """
    return workflow.create_request(actor, payload, idempotency_key)


@router.get("/{request_id}", response_model=RequestResponse)
def request_details(
    request_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    return workflow.get_request(actor, request_id)


@router.get("/{request_id}/history", response_model=list[RequestEventResponse])
def request_history(
    request_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    """Request events in chronological order, with the same access as the card."""
    return workflow.request_history(actor, request_id)


@router.patch("/{request_id}/review", response_model=RequestResponse)
def review_request(
    request_id: UUID,
    payload: RequestReview,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Manager of the employee or HR decides; nobody can review their own request.

    An identical retry by the same reviewer is safe and creates no new events.
    A different decision/reviewer/comment after a decision returns 409.
    """
    return workflow.review_request(actor, request_id, payload)


@router.post("/{request_id}/cancel", response_model=RequestResponse)
def cancel_request(
    request_id: UUID,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    """Owner withdraws a pending request; identical retries have no side effects."""
    return workflow.cancel_request(actor, request_id)
