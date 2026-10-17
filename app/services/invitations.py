"""Invitation authority lives in service-only database functions, never metadata."""
import hashlib
import logging
import secrets

from fastapi import HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.db.supabase import get_supabase_client
from app.schemas.auth import IssueInvitationRequest
from app.schemas.common import UserContext

logger = logging.getLogger(__name__)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _rpc(name: str, params: dict) -> dict:
    try:
        return get_supabase_client().rpc(name, params).execute().data
    except APIError as exc:
        if exc.code in {"PT403", "PT404", "PT409", "PT410", "PT422", "PT429"}:
            headers = {"Retry-After": "60"} if exc.code == "PT429" else None
            raise HTTPException(status_code=int(exc.code[2:]), detail=exc.message, headers=headers) from exc
        if exc.code in {"PGRST202", "42P01", "42703"}:
            raise HTTPException(status_code=503, detail="Invitation registration is not configured. Contact HR") from exc
        logger.warning("Invitation database operation failed (code=%s)", exc.code)
        raise HTTPException(status_code=503, detail="Registration is temporarily unavailable. Try again later") from exc
    except (HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Registration is temporarily unavailable. Try again later") from exc


def check(code: str, *, allow_consumed: bool = False) -> dict:
    return _rpc("check_registration_invitation", {"p_token_hash": code_hash(code), "p_allow_consumed": allow_consumed})


def prepare(code: str, first_name: str | None = None, last_name: str | None = None, *, resend: bool = False) -> dict:
    return _rpc("prepare_registration_invitation", {"p_token_hash": code_hash(code), "p_first_name": first_name,
        "p_last_name": last_name, "p_resend": resend})


def complete(code: str, auth_user_id: str, first_name: str | None = None, last_name: str | None = None) -> dict:
    return _rpc("complete_registration_invitation", {"p_token_hash": code_hash(code), "p_auth_user_id": auth_user_id,
        "p_first_name": first_name, "p_last_name": last_name})


def issue(actor: UserContext, payload: IssueInvitationRequest) -> dict:
    if actor.role != "hr_admin":
        raise HTTPException(status_code=403, detail="HR administrator role required")
    # 192 random bits; prefix is visual only. Code returned once, never logged.
    code = "JP-" + secrets.token_urlsafe(24)
    result = _rpc("issue_registration_invitation", {"p_actor_id": actor.id, "p_token_hash": code_hash(code),
        "p_details": payload.model_dump(mode="json")})
    return {**result, "invitation_code": code}


def revoke(actor: UserContext, invitation_id: str) -> dict:
    if actor.role != "hr_admin":
        raise HTTPException(status_code=403, detail="HR administrator role required")
    return _rpc("revoke_registration_invitation", {"p_actor_id": actor.id,"p_invitation_id": invitation_id})


def list_invitations(actor: UserContext) -> list[dict]:
    if actor.role != "hr_admin":
        raise HTTPException(status_code=403, detail="HR administrator role required")
    return _rpc("list_registration_invitations", {"p_actor_id": actor.id})
