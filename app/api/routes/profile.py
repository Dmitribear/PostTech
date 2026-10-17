from fastapi import APIRouter, Depends, HTTPException, status
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.core.permissions import ensure_can_view_profile, get_profile
from app.core.security import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext
from app.schemas.profile import EmployeeDashboard
from app.services.learning import get_assigned_courses
from app.services.notifications import list_employee_notifications

router = APIRouter(tags=["profile"])


def _public_profile(profile: dict) -> dict:
    return {key: value for key, value in profile.items() if key != "auth_user_id"}


@router.get("/profile", response_model=EmployeeDashboard)
def my_profile(actor: UserContext = Depends(get_current_user)) -> dict:
    """Return the employee's HR fields, manager's name, assigned learning and notifications."""
    try:
        profile = get_profile(actor.id)
        ensure_can_view_profile(actor, profile)
        client = get_supabase_client()
        manager = None
        if profile.get("manager_id"):
            result = (
                client.table("employee_profiles")
                .select("id,full_name")
                .eq("id", str(profile["manager_id"]))
                .limit(1)
                .execute()
            )
            manager = (result.data or [None])[0]
        return {
            **_public_profile(profile),
            "manager": manager,
            "assigned_courses": get_assigned_courses(client, actor.id),
            "notifications": list_employee_notifications(client, actor.id),
        }
    except (RuntimeError, HTTPError, APIError) as exc:
        raise HTTPException(status_code=503, detail="Employee profile is temporarily unavailable") from exc


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
