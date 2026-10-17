from fastapi import APIRouter, Depends, HTTPException, status

from app.core.permissions import ensure_can_view_profile, get_profile
from app.core.security import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext

router = APIRouter(tags=["profile"])


def _public_profile(profile: dict) -> dict:
    return {key: value for key, value in profile.items() if key != "auth_user_id"}


@router.get("/profile")
def my_profile(actor: UserContext = Depends(get_current_user)) -> dict:
    """Return the signed-in employee's read-only HR profile."""
    profile = get_profile(actor.id)
    ensure_can_view_profile(actor, profile)
    return _public_profile(profile)


@router.get("/employees/{employee_id}")
def employee_profile(
    employee_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    profile = get_profile(employee_id)
    ensure_can_view_profile(actor, profile)
    return _public_profile(profile)


@router.get("/team")
def team_profiles(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    if actor.role == "hr_admin":
        response = get_supabase_client().table("employee_profiles").select("*").order("full_name").execute()
        return [_public_profile(profile) for profile in response.data or []]
    if actor.role not in ("manager", "director"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager, director or HR role required")

    client = get_supabase_client()
    direct_reports = (
        client.table("employee_profiles")
        .select("*")
        .eq("manager_id", actor.id)
        .order("full_name")
        .execute()
        .data
        or []
    )
    return [_public_profile(profile) for profile in direct_reports]
