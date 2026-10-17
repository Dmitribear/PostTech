from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.core.security import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.admin import AdminEmployee, EmployeeRoleResult, EmployeeRoleUpdate
from app.schemas.common import UserContext

router = APIRouter(prefix="/admin", tags=["HR administration"])


def require_hr_admin(actor: UserContext = Depends(get_current_user)) -> UserContext:
    if actor.role != "hr_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="HR administrator role required")
    return actor


@router.get("/employees", response_model=list[AdminEmployee])
def list_employees(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    actor: UserContext = Depends(require_hr_admin),
) -> list[dict]:
    """List employee profiles for role administration; never return Auth IDs or credentials."""
    try:
        result = (
            get_supabase_client()
            .table("employee_profiles")
            .select("id,full_name,email,role,manager_id")
            .order("full_name")
            .order("id")
            .range(offset, offset + limit - 1)
            .execute()
        )
    except (RuntimeError, HTTPError, APIError) as exc:
        raise HTTPException(status_code=503, detail="Employee storage is temporarily unavailable") from exc
    return result.data or []


@router.patch("/employees/{employee_id}/role", response_model=EmployeeRoleResult)
def assign_role(
    employee_id: UUID,
    payload: EmployeeRoleUpdate,
    actor: UserContext = Depends(require_hr_admin),
) -> dict:
    """Assign an access role, leaving official HR fields unchanged (migration 0004 required)."""
    if str(employee_id) == actor.id and payload.role != "hr_admin":
        raise HTTPException(status_code=409, detail="You cannot remove your own HR administrator role")
    try:
        # The transaction rechecks the caller's CURRENT role and serializes role
        # changes, so two administrators cannot concurrently demote one another.
        result = get_supabase_client().rpc(
            "assign_employee_role",
            {"p_actor_id": actor.id, "p_employee_id": str(employee_id), "p_role": payload.role},
        ).execute()
    except APIError as exc:
        failures = {
            "42501": (403, "HR administrator role required"),
            "P0002": (404, "Employee not found"),
            "PT409": (409, "You cannot remove your own HR administrator role"),
            "PT412": (409, "Reassign this employee's direct reports before removing their supervisor role"),
        }
        error_status, detail = failures.get(
            exc.code, (503, "Role administration is unavailable; check database migration 0004"),
        )
        raise HTTPException(status_code=error_status, detail=detail) from exc
    except (RuntimeError, HTTPError) as exc:
        raise HTTPException(status_code=503, detail="Role administration is temporarily unavailable") from exc
    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=503, detail="Role administration did not return a result")
    return rows[0]

