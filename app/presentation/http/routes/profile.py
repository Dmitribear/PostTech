from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.dto.profile import EmployeeDashboard
from app.application.use_cases import profile as use_cases
from app.domain.models import UserContext
from app.presentation.http.responses import render_result
from app.presentation.http.security import get_current_user

router = APIRouter(tags=["profile"])


@router.get("/profile", response_model=EmployeeDashboard)
def my_profile(actor: UserContext = Depends(get_current_user)) -> dict:
    return render_result(use_cases.my_profile(actor=actor))


@router.get("/employees/{employee_id}")
def employee_profile(
    employee_id: str, actor: UserContext = Depends(get_current_user)
) -> dict:
    return render_result(
        use_cases.employee_profile(employee_id=employee_id, actor=actor)
    )


@router.get("/team")
def team_profiles(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    return render_result(use_cases.team_profiles(actor=actor))


@router.get("/team/page")
def team_page(
    after: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    actor: UserContext = Depends(get_current_user),
) -> dict:
    return use_cases.team_page(actor, str(after) if after else None, limit)
