from app.application.dependencies import get_data_gateway
from app.application.use_cases.learning import get_assigned_courses
from app.application.use_cases.notification_delivery import list_employee_notifications
from app.application.use_cases.permissions import ensure_can_view_profile, get_profile
from app.domain.errors import ApplicationError, StorageError, StorageUnavailable
from app.domain.models import UserContext


def team_page(actor: UserContext, after: str | None = None, limit: int = 50) -> dict:
    if actor.role not in ("manager", "director", "hr_admin"):
        raise ApplicationError(403, "Manager or HR role required")
    if not 1 <= limit <= 100:
        raise ApplicationError(422, "Page size must be between 1 and 100")
    query = get_data_gateway().table("employee_profiles").select("*")
    if actor.role != "hr_admin":
        query = query.eq("manager_id", actor.id)
    if after:
        query = query.gt("id", after)
    rows = query.order("id").limit(limit + 1).execute().data or []
    return {
        "items": [_public_profile(row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


def _public_profile(profile: dict) -> dict:
    return {key: value for key, value in profile.items() if key != "auth_user_id"}


def _with_manager(profile: dict) -> dict:
    """Only the reporting line is public; never return a manager's HR record."""
    result = _public_profile(profile)
    result["manager_name"] = None
    if profile.get("manager_id"):
        managers = (
            get_data_gateway()
            .table("employee_profiles")
            .select("id,full_name")
            .eq("id", profile["manager_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        result["manager_name"] = managers[0]["full_name"] if managers else None
    return result


def my_profile(actor: UserContext = None) -> dict:
    profile = get_profile(actor.id)
    ensure_can_view_profile(actor, profile)
    try:
        result = _with_manager(profile)
        client = get_data_gateway()
        result["manager"] = (
            {"id": profile["manager_id"], "full_name": result["manager_name"]}
            if result["manager_name"]
            else None
        )
        result["assigned_courses"] = get_assigned_courses(client, actor.id)
        result["notifications"] = list_employee_notifications(client, actor.id)
        return result
    except (RuntimeError, StorageUnavailable, StorageError) as exc:
        raise ApplicationError(
            503, "Employee profile is temporarily unavailable"
        ) from exc


def employee_profile(employee_id: str, actor: UserContext = None) -> dict:
    profile = get_profile(employee_id)
    ensure_can_view_profile(actor, profile)
    return _with_manager(profile)


def team_profiles(actor: UserContext = None) -> list[dict]:
    if actor.role == "hr_admin":
        response = (
            get_data_gateway()
            .table("employee_profiles")
            .select("*")
            .order("full_name")
            .execute()
        )
        return [_public_profile(profile) for profile in response.data or []]
    if actor.role not in ("manager", "director"):
        raise ApplicationError(status_code=403, detail="Manager or HR role required")
    response = (
        get_data_gateway()
        .table("employee_profiles")
        .select("*")
        .eq("manager_id", actor.id)
        .order("full_name")
        .execute()
    )
    return [_public_profile(profile) for profile in response.data or []]
