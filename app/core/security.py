from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase_auth.errors import AuthApiError, AuthInvalidJwtError, AuthSessionMissingError

from app.core.permissions import get_profile_by_auth_id
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserContext:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        auth_response = get_supabase_client().auth.get_user(credentials.credentials)
        auth_user = auth_response.user
    except (AuthInvalidJwtError, AuthSessionMissingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthApiError as exc:
        # A rejected credential differs from a network/service failure. Only
        # explicit token/session errors should trigger the browser's refresh.
        if exc.status == 401 or exc.code in {
            "bad_jwt", "invalid_jwt", "no_authorization", "user_not_found", "session_not_found",
        }:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth is temporarily unavailable",
        ) from exc
    except Exception as exc:
        # Includes SDK retryable errors, transport failures and malformed
        # upstream responses. Fail closed without blaming valid credentials
        # or returning exception bodies that may contain internal details.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth is temporarily unavailable",
        ) from exc

    if auth_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        profile = get_profile_by_auth_id(str(auth_user.id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HR database is unavailable; retry later",
        ) from exc
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no HR profile; contact an administrator",
        )

    return UserContext(
        id=str(profile["id"]),
        auth_user_id=str(auth_user.id),
        role=profile["role"],
        manager_id=str(profile["manager_id"]) if profile.get("manager_id") else None,
    )
