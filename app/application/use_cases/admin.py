from uuid import UUID

from app.application.dependencies import get_data_gateway
from app.application.dto.admin import (
    EmployeeRoleUpdate,
)
from app.domain.errors import ApplicationError, StorageError, StorageUnavailable
from app.domain.models import UserContext


def require_hr_admin(actor: UserContext = None) -> UserContext:
    if actor.role != "hr_admin":
        raise ApplicationError(status_code=403, detail="HR administrator role required")
    return actor


def list_employees(
    offset: int = 0, limit: int = 50, actor: UserContext = None
) -> list[dict]:
    require_hr_admin(actor)
    try:
        result = (
            get_data_gateway()
            .table("employee_profiles")
            .select("id,full_name,email,role,manager_id")
            .order("full_name")
            .order("id")
            .range(offset, offset + limit - 1)
            .execute()
        )
    except (RuntimeError, StorageUnavailable, StorageError) as exc:
        raise ApplicationError(
            status_code=503, detail="Employee storage is temporarily unavailable"
        ) from exc
    return result.data or []


def assign_role(
    employee_id: UUID, payload: EmployeeRoleUpdate, actor: UserContext = None
) -> dict:
    require_hr_admin(actor)
    if str(employee_id) == actor.id and payload.role != "hr_admin":
        raise ApplicationError(
            status_code=409, detail="You cannot remove your own HR administrator role"
        )
    try:
        result = (
            get_data_gateway()
            .rpc(
                "assign_employee_role",
                {
                    "p_actor_id": actor.id,
                    "p_employee_id": str(employee_id),
                    "p_role": payload.role,
                },
            )
            .execute()
        )
    except StorageError as exc:
        failures = {
            "42501": (403, "HR administrator role required"),
            "P0002": (404, "Employee not found"),
            "PT409": (409, "You cannot remove your own HR administrator role"),
            "PT412": (
                409,
                "Reassign this employee's direct reports before removing their supervisor role",
            ),
        }
        error_status, detail = failures.get(
            exc.code,
            (503, "Role administration is unavailable; check database migration 0015"),
        )
        raise ApplicationError(status_code=error_status, detail=detail) from exc
    except (RuntimeError, StorageUnavailable) as exc:
        raise ApplicationError(
            status_code=503, detail="Role administration is temporarily unavailable"
        ) from exc
    rows = result.data or []
    if not rows:
        raise ApplicationError(
            status_code=503, detail="Role administration did not return a result"
        )
    return rows[0]
