from typing import Any

from fastapi import APIRouter, HTTPException, status
from supabase_auth.errors import AuthApiError, AuthRetryableError

from app.db.supabase import get_supabase_auth_client
from app.schemas.auth import Credentials, RefreshRequest

router = APIRouter(prefix="/auth", tags=["authentication"])


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
    raw_message = getattr(exc, "message", None) or str(exc)
    message = str(raw_message).strip()
    if not message or message in {"None", "AuthApiError"}:
        return "Registration failed. Check the email, password, and Supabase Auth settings."
    return f"Registration failed: {message}. Check the email, password, and Supabase Auth settings."


def _session_payload(session: Any) -> dict[str, Any]:
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": session.token_type,
        "expires_in": session.expires_in,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials) -> dict[str, Any]:
    """Create a Supabase Auth account; HR profile linking is an admin action."""
    client = _auth_client()
    try:
        response = client.auth.sign_up(
            {
                "email": payload.email,
                "password": payload.password.get_secret_value(),
            }
        )
    except AuthApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_registration_error_detail(exc),
        ) from exc
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
        "email": user.email if user else payload.email,
        "email_confirmation_required": session is None,
        "message": (
            "Confirm your email, then sign in. HR must link your account to an employee profile before API access."
            if session is None
            else "Account created. HR must link your account to an employee profile before API access."
        ),
    }
    if session is not None:
        result.update(_session_payload(session))
    return result


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
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


@router.post("/refresh")
def refresh_session(payload: RefreshRequest) -> dict[str, Any]:
    """Exchange a refresh token for a fresh Supabase Auth session."""
    client = _auth_client()
    try:
        response = client.auth.refresh_session(
            payload.refresh_token.get_secret_value()
        )
    except AuthApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc
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
