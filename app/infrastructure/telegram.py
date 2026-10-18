"""Telegram transport shares portal identities and data; all state lives in SQL."""

import hashlib
import re
import secrets

from fastapi import HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.domain.models import UserContext
from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client


def bot_username() -> str | None:
    name = get_settings().telegram_bot_username.strip().lstrip("@")
    return (
        name
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", name)
        and name.lower().endswith("bot")
        else None
    )


def configured() -> bool:
    secret = get_settings().telegram_worker_secret
    return bool(bot_username() and secret and len(secret.get_secret_value()) >= 32)


def _rpc(name: str, params: dict):
    try:
        return get_supabase_client().rpc(name, params).execute().data
    except APIError as exc:
        if exc.code in {"PT401", "PT403", "PT404", "PT409", "PT410", "PT422", "PT429"}:
            raise HTTPException(
                status_code=int(exc.code[2:]), detail=exc.message
            ) from exc
        raise HTTPException(
            status_code=503, detail="Telegram is temporarily unavailable"
        ) from exc
    except (HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503, detail="Telegram is temporarily unavailable"
        ) from exc


def status(actor: UserContext) -> dict:
    result = _rpc("telegram_status", {"p_actor_id": actor.id})
    return {**result, "enabled": configured(), "bot_username": bot_username()}


def issue_link(actor: UserContext) -> dict:
    if not configured():
        raise HTTPException(
            status_code=503, detail="Telegram integration is not configured"
        )
    code = secrets.token_urlsafe(32)
    result = _rpc(
        "issue_telegram_link",
        {
            "p_actor_id": actor.id,
            "p_code_hash": hashlib.sha256(code.encode()).hexdigest(),
        },
    )
    return {
        "url": f"https://t.me/{bot_username()}?start={code}",
        "expires_at": result["expires_at"],
    }


def consume_link(payload) -> dict:
    return _rpc(
        "consume_telegram_link",
        {
            "p_code_hash": hashlib.sha256(payload.code.encode()).hexdigest(),
            "p_telegram_user_id": payload.telegram_user_id,
            "p_chat_id": payload.chat_id,
            "p_username": payload.username,
        },
    )


def resolve_actor(telegram_user_id: int) -> UserContext:
    profile = _rpc("resolve_telegram_actor", {"p_telegram_user_id": telegram_user_id})
    return UserContext(**profile)


def unlink(actor: UserContext) -> dict:
    return _rpc("unlink_telegram", {"p_actor_id": actor.id})


def settings(actor: UserContext, notifications_enabled: bool) -> dict:
    _rpc(
        "set_telegram_settings",
        {"p_actor_id": actor.id, "p_notifications_enabled": notifications_enabled},
    )
    return status(actor)


def claim_outbox(limit: int) -> list[dict]:
    return _rpc("claim_telegram_outbox", {"p_limit": limit}) or []


def acknowledge(delivery_id: str, payload) -> dict:
    return _rpc(
        "ack_telegram_outbox",
        {
            "p_delivery_id": delivery_id,
            "p_lease_token": str(payload.lease_token),
            "p_status": payload.status,
            "p_retry_after_seconds": payload.retry_after_seconds,
        },
    )


def worker_state(bot_id: int, offset: int | None = None) -> dict:
    return _rpc("telegram_worker_offset", {"p_bot_id": bot_id, "p_offset": offset})
