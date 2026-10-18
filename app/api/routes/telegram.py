from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.core.security import get_current_user, get_website_user, require_telegram_worker
from app.schemas.common import UserContext
from app.schemas.telegram import (
    ConsumeTelegramLink, TelegramAcknowledgement, TelegramLinkResponse,
    TelegramSettings, TelegramStatus, TelegramWorkerState,
)
from app.services import telegram

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get("/status", response_model=TelegramStatus)
def status(actor: UserContext = Depends(get_current_user)):
    return telegram.status(actor)


@router.post("/link", response_model=TelegramLinkResponse)
def issue_link(response: Response, actor: UserContext = Depends(get_website_user)):
    response.headers["Cache-Control"] = "no-store"
    return telegram.issue_link(actor)


@router.delete("/link")
def unlink(actor: UserContext = Depends(get_current_user)):
    return telegram.unlink(actor)


@router.patch("/settings", response_model=TelegramStatus)
def settings(payload: TelegramSettings, actor: UserContext = Depends(get_current_user)):
    return telegram.settings(actor, payload.notifications_enabled)


@router.post("/consume-link", dependencies=[Depends(require_telegram_worker)])
def consume_link(payload: ConsumeTelegramLink):
    return telegram.consume_link(payload)


@router.get("/outbox", dependencies=[Depends(require_telegram_worker)])
def outbox(response: Response, limit: int = Query(default=20, ge=1, le=100)):
    response.headers["Cache-Control"] = "no-store"
    return telegram.claim_outbox(limit)


@router.post("/outbox/{delivery_id}/ack", dependencies=[Depends(require_telegram_worker)])
def acknowledge(delivery_id: UUID, payload: TelegramAcknowledgement):
    return telegram.acknowledge(str(delivery_id), payload)


@router.get("/worker-state", response_model=TelegramWorkerState, dependencies=[Depends(require_telegram_worker)])
def get_worker_state(bot_id: int = Query(gt=0, lt=2**63)):
    return telegram.worker_state(bot_id)


@router.patch("/worker-state", response_model=TelegramWorkerState, dependencies=[Depends(require_telegram_worker)])
def set_worker_state(payload: TelegramWorkerState):
    return telegram.worker_state(payload.bot_id, payload.offset)
