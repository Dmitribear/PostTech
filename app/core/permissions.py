from fastapi import HTTPException, status

from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext


def get_profile_by_auth_id(auth_user_id: str) -> dict | None:
    response = (
        get_supabase_client()
        .table("employee_profiles")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .limit(1)
        .execute()
    )
    profiles = response.data or []
    return profiles[0] if profiles else None


def get_profile(employee_id: str) -> dict:
    response = (
        get_supabase_client()
        .table("employee_profiles")
        .select("*")
        .eq("id", employee_id)
        .limit(1)
        .execute()
    )
    profiles = response.data or []
    if not profiles:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return profiles[0]


def ensure_can_view_profile(actor: UserContext, profile: dict) -> None:
    if actor.role == "hr_admin" or profile["id"] == actor.id:
        return
    if actor.role == "manager" and profile.get("manager_id") == actor.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access to this employee is forbidden")


def ensure_can_manage_employee(actor: UserContext, employee_id: str) -> dict:
    profile = get_profile(employee_id)
    if actor.role == "hr_admin":
        return profile
    if actor.role == "manager" and profile.get("manager_id") == actor.id:
        return profile
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot manage this employee")
