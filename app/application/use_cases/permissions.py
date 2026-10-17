from app.application.dependencies import get_data_gateway
from app.domain.errors import ApplicationError
from app.domain.models import UserContext


def get_profile_by_auth_id(auth_user_id: str) -> dict | None:
    response = (
        get_data_gateway()
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
        get_data_gateway()
        .table("employee_profiles")
        .select("*")
        .eq("id", employee_id)
        .limit(1)
        .execute()
    )
    profiles = response.data or []
    if not profiles:
        raise ApplicationError(status_code=404, detail="Employee not found")
    return profiles[0]


def ensure_can_view_profile(actor: UserContext, profile: dict) -> None:
    if actor.role == "hr_admin" or profile["id"] == actor.id:
        return
    if actor.role in ("manager", "director") and profile.get("manager_id") == actor.id:
        return
    raise ApplicationError(
        status_code=403, detail="Access to this employee is forbidden"
    )


def ensure_can_manage_employee(actor: UserContext, employee_id: str) -> dict:
    profile = get_profile(employee_id)
    if actor.role == "hr_admin":
        return profile
    if actor.role in ("manager", "director") and profile.get("manager_id") == actor.id:
        return profile
    raise ApplicationError(status_code=403, detail="You cannot manage this employee")
