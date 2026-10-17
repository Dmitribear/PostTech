from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.application.dto.digital_hr import (
    CourseAssignmentCreate,
    CourseProgressUpdate,
    QuizSubmission,
)
from app.application.use_cases import academy
from app.domain.models import UserContext
from app.presentation.http.security import get_current_user

router = APIRouter(prefix="/academy", tags=["Jana Academy"])


@router.get("/courses")
def list_courses(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    return academy.list_courses(actor)


@router.get("/my-courses")
def my_courses(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    return academy.my_courses(actor)


@router.get("/team")
def team_courses(
    employee_id: UUID | None = None,
    course_id: UUID | None = None,
    actor: UserContext = Depends(get_current_user),
) -> list[dict]:
    return academy.team_courses(actor, employee_id, course_id)


@router.get("/courses/{course_id}")
def course_details(
    course_id: UUID, actor: UserContext = Depends(get_current_user)
) -> dict:
    return academy.course_details(actor, course_id)


@router.get("/courses/{course_id}/attempts")
def course_attempts(
    course_id: UUID, actor: UserContext = Depends(get_current_user)
) -> list[dict]:
    return academy.course_attempts(actor, course_id)


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def assign_course(
    payload: CourseAssignmentCreate, actor: UserContext = Depends(get_current_user)
) -> dict:
    return academy.assign_course(
        actor, payload.employee_id, payload.course_id, payload.due_on
    )


@router.patch("/courses/{course_id}/progress")
def update_progress(
    course_id: UUID,
    payload: CourseProgressUpdate,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    return academy.update_progress(actor, course_id, payload.progress_percent)


@router.post("/courses/{course_id}/complete")
def complete_course(
    course_id: UUID,
    payload: QuizSubmission,
    idempotency_key: UUID | None = Header(default=None, alias="Idempotency-Key"),
    actor: UserContext = Depends(get_current_user),
) -> dict:
    return academy.complete_course(actor, course_id, payload.answers, idempotency_key)
