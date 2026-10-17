"""Invitation authority lives in service-only database functions, never metadata."""

import hashlib
import logging
import secrets

from app.application import email_delivery as invitation_email
from app.application.dependencies import get_data_gateway
from app.application.dto.auth import IssueInvitationRequest
from app.domain.errors import ApplicationError, StorageError, StorageUnavailable
from app.domain.models import UserContext

logger = logging.getLogger(__name__)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _rpc(name: str, params: dict) -> dict:
    try:
        return get_data_gateway().rpc(name, params).execute().data
    except StorageError as exc:
        if exc.code in {"PT403", "PT404", "PT409", "PT410", "PT422", "PT429"}:
            headers = {"Retry-After": "60"} if exc.code == "PT429" else None
            raise ApplicationError(
                status_code=int(exc.code[2:]), detail=exc.message, headers=headers
            ) from exc
        if exc.code in {"PGRST202", "42P01", "42703"}:
            raise ApplicationError(
                status_code=503,
                detail="Invitation registration is not configured. Contact HR",
            ) from exc
        logger.warning("Invitation database operation failed (code=%s)", exc.code)
        raise ApplicationError(
            status_code=503,
            detail="Registration is temporarily unavailable. Try again later",
        ) from exc
    except (StorageUnavailable, RuntimeError) as exc:
        raise ApplicationError(
            status_code=503,
            detail="Registration is temporarily unavailable. Try again later",
        ) from exc


def check(code: str, *, allow_consumed: bool = False) -> dict:
    return _rpc(
        "check_registration_invitation",
        {"p_token_hash": code_hash(code), "p_allow_consumed": allow_consumed},
    )


def prepare(
    code: str,
    first_name: str | None = None,
    last_name: str | None = None,
    *,
    resend: bool = False,
) -> dict:
    return _rpc(
        "prepare_registration_invitation",
        {
            "p_token_hash": code_hash(code),
            "p_first_name": first_name,
            "p_last_name": last_name,
            "p_resend": resend,
        },
    )


def complete(
    code: str,
    auth_user_id: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> dict:
    return _rpc(
        "complete_registration_invitation",
        {
            "p_token_hash": code_hash(code),
            "p_auth_user_id": auth_user_id,
            "p_first_name": first_name,
            "p_last_name": last_name,
        },
    )


def issue(actor: UserContext, payload: IssueInvitationRequest) -> dict:
    if actor.role != "hr_admin":
        raise ApplicationError(status_code=403, detail="HR administrator role required")
    # 192 random bits; prefix is visual only. Code returned once, never logged.
    code = "JP-" + secrets.token_urlsafe(24)
    result = _rpc(
        "issue_registration_invitation",
        {
            "p_actor_id": actor.id,
            "p_token_hash": code_hash(code),
            "p_details": payload.model_dump(mode="json"),
        },
    )
    if not invitation_email.configured():
        return {**result, "invitation_code": code, "email_status": "not_configured"}
    try:
        return _send(actor, result["id"], code)
    except ApplicationError:
        # Creation is already committed. Preserve the recoverable code if the
        # separate delivery transaction is unavailable; never suggest re-creation.
        logger.warning("Created invitation could not start email delivery")
        return {**result, "invitation_code": code, "email_status": "not_sent"}


def _send(actor: UserContext, invitation_id: str, code: str) -> dict:
    digest = code_hash(code)
    result = _rpc(
        "begin_invitation_email",
        {
            "p_actor_id": actor.id,
            "p_invitation_id": invitation_id,
            "p_token_hash": digest,
        },
    )
    status = invitation_email.send(result, code, digest)
    try:
        _rpc(
            "finish_invitation_email",
            {
                "p_invitation_id": invitation_id,
                "p_token_hash": digest,
                "p_status": status,
            },
        )
    except ApplicationError:
        # Sending may have succeeded; don't turn this into a duplicate create attempt.
        logger.warning("Invitation email status could not be recorded")
    return {**result, "invitation_code": code, "email_status": status}


def resend(actor: UserContext, invitation_id: str) -> dict:
    if actor.role != "hr_admin":
        raise ApplicationError(status_code=403, detail="HR administrator role required")
    if not invitation_email.configured():
        raise ApplicationError(
            status_code=503, detail="Invitation email sender is not configured"
        )
    # No plaintext secret is persisted. Re-sending rotates the code, not the role/email.
    return _send(actor, invitation_id, "JP-" + secrets.token_urlsafe(24))


def revoke(actor: UserContext, invitation_id: str) -> dict:
    if actor.role != "hr_admin":
        raise ApplicationError(status_code=403, detail="HR administrator role required")
    return _rpc(
        "revoke_registration_invitation",
        {"p_actor_id": actor.id, "p_invitation_id": invitation_id},
    )


def list_invitations(actor: UserContext) -> list[dict]:
    if actor.role != "hr_admin":
        raise ApplicationError(status_code=403, detail="HR administrator role required")
    return _rpc("list_registration_invitations", {"p_actor_id": actor.id})
