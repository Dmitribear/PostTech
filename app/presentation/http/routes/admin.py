from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.dto.admin import (
    AdminEmployee,
    EmployeeRoleResult,
    EmployeeRoleUpdate,
)
from app.application.use_cases import admin as use_cases
from app.domain.models import UserContext
from app.presentation.http.responses import render_result
from app.presentation.http.security import get_current_user

router = APIRouter(prefix="/admin", tags=["HR administration"])


def require_hr_admin(actor: UserContext = Depends(get_current_user)) -> UserContext:
    return use_cases.require_hr_admin(actor)


@router.get("/employees", response_model=list[AdminEmployee])
def list_employees(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    actor: UserContext = Depends(require_hr_admin),
) -> list[dict]:
    return render_result(
        use_cases.list_employees(offset=offset, limit=limit, actor=actor)
    )


@router.patch("/employees/{employee_id}/role", response_model=EmployeeRoleResult)
def assign_role(
    employee_id: UUID,
    payload: EmployeeRoleUpdate,
    actor: UserContext = Depends(require_hr_admin),
) -> dict:
    return render_result(
        use_cases.assign_role(employee_id=employee_id, payload=payload, actor=actor)
    )
