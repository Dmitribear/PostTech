from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from supabase_auth.errors import AuthApiError, AuthRetryableError, AuthWeakPasswordError

from app.core.security import get_current_user
from app.db.supabase import create_supabase_auth_client as get_supabase_auth_client
from app.schemas.auth import (CompleteInvitationRequest, Credentials, InvitationCode,
    IssueInvitationRequest, RefreshRequest, RegistrationRequest, VerifyRegistrationRequest,
    ConfirmPasswordResetRequest, PasswordResetRequest)
from app.schemas.common import UserContext
from app.services import invitations, password_recovery

class SensitiveAuthRoute(APIRoute):
    """Validation errors must not echo passwords, OTPs, or invitation codes."""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def without_secret_inputs(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse(status_code=422, content={"detail": [
                    {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                    for error in exc.errors()
                ]})
        return without_secret_inputs


router = APIRouter(prefix="/auth", tags=["authentication"], route_class=SensitiveAuthRoute)


def _auth_client():
    try:
        return get_supabase_auth_client()
    except RuntimeError as exc:
        detail = str(exc)
        lowered = detail.lower()
        if any(keyword in lowered for keyword in ("look swapped", "looks swapped", "looks wrong")):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=detail,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth is not configured",
        ) from exc


def _registration_error_detail(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code in {"user_already_exists", "email_exists"}:
        return "An account already exists. Confirm your email, then continue with your password"
    if code in {"email_address_not_authorized", "over_email_send_rate_limit"}:
        return "Confirmation email could not be sent. Contact HR or try again later"
    return "Could not create your account. Check your password or contact HR"


def _session_payload(session: Any) -> dict[str, Any]:
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": session.token_type,
        "expires_in": session.expires_in,
    }


def _auth_error(exc: AuthApiError, detail: str, status_code: int = 400) -> HTTPException:
    if getattr(exc, "status", None) == 429 or getattr(exc, "code", None) in {"over_request_rate_limit", "over_email_send_rate_limit"}:
        return HTTPException(status_code=429, detail="Please wait 60 seconds before trying again", headers={"Retry-After": "60"})
    return HTTPException(status_code=status_code, detail=detail,
        headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None)


def _activate(code: str, response: Any, first_name: str | None = None, last_name: str | None = None) -> dict[str, Any]:
    user, session = response.user, response.session
    if user is None or session is None or not getattr(user, "email_confirmed_at", None):
        raise HTTPException(status_code=403, detail="Confirm the invited email before activating your workspace")
    if first_name is not None or last_name is not None:
        invitations.complete(code, str(user.id), first_name, last_name)
    else:
        invitations.complete(code, str(user.id))
    return {"user_id": str(user.id), "email": user.email, **_session_payload(session)}


@router.post("/invitations/check")
def check_invitation(payload: InvitationCode) -> dict[str, Any]:
    return invitations.check(payload.invitation_code)


@router.post("/invitations", status_code=201)
def issue_invitation(payload: IssueInvitationRequest, actor: UserContext = Depends(get_current_user)) -> dict[str, Any]:
    """Issue a code for HR to deliver through an approved channel; sends no mail."""
    return invitations.issue(actor, payload)


@router.delete("/invitations/{invitation_id}")
@router.post("/invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: UUID, actor: UserContext = Depends(get_current_user)) -> dict[str, Any]:
    return invitations.revoke(actor, str(invitation_id))


@router.get("/invitations")
def list_invitations(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    return invitations.list_invitations(actor)


@router.post("/invitations/{invitation_id}/send")
def send_invitation(invitation_id: UUID, actor: UserContext = Depends(get_current_user)) -> dict[str, Any]:
    return invitations.resend(actor, str(invitation_id))


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest) -> dict[str, Any]:
    """Register the invitation's immutable email; only verified Auth can activate."""
    client = _auth_client()
    invitation = invitations.prepare(payload.invitation_code, payload.first_name, payload.last_name)
    try:
        response = client.auth.sign_up(
            {
                "email": invitation["email"],
                "password": payload.password.get_secret_value(),
            }
        )
    except AuthApiError as exc:
        raise _auth_error(exc, _registration_error_detail(exc)) from exc
    except AuthRetryableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth is temporarily unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not complete registration with Supabase Auth",
        ) from exc

    user = response.user
    session = response.session
    result: dict[str, Any] = {
        "user_id": str(user.id) if user else None,
        "email": invitation["email"],
        "email_confirmation_required": session is None,
        "message": (
            "Check your email to activate your workspace"
            if session is None
            else "Your workspace is ready"
        ),
    }
    if session is not None:
        result.update(_activate(payload.invitation_code, response))
    return result


@router.post("/verify-registration")
def verify_registration(payload: VerifyRegistrationRequest) -> dict[str, Any]:
    invitation = invitations.check(payload.invitation_code)
    try:
        response = _auth_client().auth.verify_otp({"email": invitation["email"], "token": payload.token, "type": "email"})
    except AuthApiError as exc:
        raise _auth_error(exc, "Confirmation code is invalid or expired. Request a new code") from exc
    except AuthRetryableError as exc:
        raise HTTPException(status_code=503, detail="Supabase Auth is temporarily unavailable") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not verify your email. Try again later") from exc
    return _activate(payload.invitation_code, response)


@router.post("/resend-registration")
def resend_registration(payload: InvitationCode) -> dict[str, Any]:
    client = _auth_client()
    invitation = invitations.prepare(payload.invitation_code, resend=True)
    try:
        client.auth.resend({"email": invitation["email"], "type": "signup"})
    except AuthApiError as exc:
        raise _auth_error(exc, "Confirmation email could not be sent. Contact HR or try again later") from exc
    except AuthRetryableError as exc:
        raise HTTPException(status_code=503, detail="Supabase Auth is temporarily unavailable") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Confirmation email could not be sent. Contact HR or try again later") from exc
    return {"message": "Confirmation email sent. Check your inbox and spam folder", "retry_after": 60}


@router.post("/complete-invitation")
def complete_invitation(payload: CompleteInvitationRequest) -> dict[str, Any]:
    invitation = invitations.check(payload.invitation_code, allow_consumed=True)
    if invitation["email"].casefold() != payload.email.casefold():
        raise HTTPException(status_code=403, detail="Use the email address from your invitation")
    try:
        response = _auth_client().auth.sign_in_with_password({"email": invitation["email"], "password": payload.password.get_secret_value()})
    except AuthApiError as exc:
        raise _auth_error(exc, "Confirm your email and check your password", 401) from exc
    except AuthRetryableError as exc:
        raise HTTPException(status_code=503, detail="Supabase Auth is temporarily unavailable") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not complete sign-in with Supabase Auth") from exc
    return _activate(payload.invitation_code, response, payload.first_name, payload.last_name)


@router.post("/login")
def login(payload: Credentials) -> dict[str, Any]:
    """Sign in with Supabase Auth and return bearer/refresh tokens."""
    client = _auth_client()
    try:
        response = client.auth.sign_in_with_password(
            {
                "email": payload.email,
                "password": payload.password.get_secret_value(),
            }
        )
    except AuthApiError as exc:
        raise _auth_error(exc, "Invalid email or password", 401) from exc
    except AuthRetryableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth is temporarily unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not complete sign-in with Supabase Auth",
        ) from exc

    session = response.session
    if session is None or response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign-in did not return a session. Confirm your email or check Supabase Auth settings.",
        )
    return {
        "user_id": str(response.user.id),
        "email": response.user.email,
        **_session_payload(session),
    }


@router.post("/password-reset")
def request_password_reset(payload: PasswordResetRequest, request: Request, response: Response) -> dict[str, Any]:
    """Request a recovery OTP without revealing whether the email is registered."""
    response.headers["Cache-Control"] = "no-store"
    client = _auth_client()
    peer = request.client.host if request.client else "unknown"
    if password_recovery.limiter.allow_send(payload.email, peer):
        try:
            # Recovery emails must use docs/templates/recovery.html ({{ .Token }}).
            # No redirect from untrusted input and no administrative password API.
            client.auth.reset_password_for_email(payload.email)
        except AuthApiError:
            # Supabase can return different account-specific errors, including
            # SMTP allow-list and per-address throttling. Keep the public answer
            # identical; provider delivery/configuration is an operator concern.
            pass
        except AuthRetryableError as exc:
            raise HTTPException(status_code=503, detail="Supabase Auth is temporarily unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Supabase Auth is temporarily unavailable") from exc
    return {"message": "If an account exists for this email, a password reset code will be sent",
            "retry_after": password_recovery.COOLDOWN_SECONDS}


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: ConfirmPasswordResetRequest, request: Request, response: Response) -> dict[str, str]:
    """Consume a recovery OTP and update only its verified user's password."""
    response.headers["Cache-Control"] = "no-store"
    peer = request.client.host if request.client else "unknown"
    password_recovery.limiter.check_confirmation(payload.email, peer)
    client = _auth_client()  # Fresh Auth state, not a shared login/admin client.
    verified_session = False
    password_updated = False
    try:
        try:
            verified = client.auth.verify_otp({"email": payload.email, "token": payload.token, "type": "recovery"})
        except AuthApiError as exc:
            raise _auth_error(exc, "Reset code is invalid or expired. Request a new code") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Supabase Auth is temporarily unavailable") from exc

        user, session = verified.user, verified.session
        verified_session = session is not None
        session_user = getattr(session, "user", None)
        if (user is None or session is None
                or not getattr(user, "email_confirmed_at", None)
                or not getattr(user, "email", None)
                or user.email.casefold() != payload.email.casefold()
                or session_user is None or str(session_user.id) != str(user.id)):
            raise HTTPException(status_code=400, detail="Reset code is invalid or expired. Request a new code")
        try:
            # verify_otp installed this session in this request's isolated SDK.
            # A request body / Authorization header can never replace it.
            updated = client.auth.update_user({"password": payload.password.get_secret_value()})
            if updated.user is None or str(updated.user.id) != str(user.id):
                raise RuntimeError("Unexpected password-update response")
            password_updated = True
        except (AuthApiError, AuthWeakPasswordError) as exc:
            raise HTTPException(status_code=400,
                detail="Password could not be changed. Choose a different password and request a new code") from exc
        except Exception as exc:
            # OTPs are single use. A transport failure may happen after the
            # update committed, so don't claim the old password still works.
            raise HTTPException(status_code=503,
                detail="Password update could not be confirmed. Try signing in with your new password or request a new code") from exc
    finally:
        if verified_session:
            try:
                client.auth.sign_out({"scope": "global" if password_updated else "local"})
            except Exception:
                # Never turn a completed password change into a failed one if
                # session revocation is temporarily unavailable. Tokens remain
                # server-local and are never returned or stored by this route.
                pass
    return {"message": "Password updated. Sign in with your new password"}


@router.post("/refresh")
def refresh_session(payload: RefreshRequest) -> dict[str, Any]:
    """Exchange a refresh token for a fresh Supabase Auth session."""
    client = _auth_client()
    try:
        response = client.auth.refresh_session(
            payload.refresh_token.get_secret_value()
        )
    except AuthApiError as exc:
        raise _auth_error(exc, "Invalid or expired refresh token", 401) from exc
    except AuthRetryableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth is temporarily unavailable",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not refresh the Supabase Auth session",
        ) from exc

    session = response.session
    if session is None or response.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not refresh session")
    return {
        "user_id": str(response.user.id),
        "email": response.user.email,
        **_session_payload(session),
    }
