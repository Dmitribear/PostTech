from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.permissions import ensure_can_manage_employee, get_profile
from app.core.security import get_current_user
from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext
from app.schemas.digital_hr import (
    CourseAssignmentCreate,
    CourseProgressUpdate,
    QuizSubmission,
)
from app.services.notifications import create_notification
from app.services.learning import get_assigned_courses

router = APIRouter(prefix="/academy", tags=["Jana Academy"])


def _find_assignment(course_id: str, employee_id: str) -> dict | None:
    result = (
        get_supabase_client()
        .table("course_assignments")
        .select("*")
        .eq("course_id", course_id)
        .eq("employee_id", employee_id)
        .limit(1)
        .execute()
    )
    assignments = result.data or []
    return assignments[0] if assignments else None


def _get_course(course_id: str) -> dict:
    result = (
        get_supabase_client()
        .table("courses")
        .select("*")
        .eq("id", course_id)
        .eq("active", True)
        .limit(1)
        .execute()
    )
    courses = result.data or []
    if not courses:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return courses[0]


def _public_quiz(quiz: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in question.items() if key != "answer_index"}
        for question in quiz
    ]


@router.get("/courses")
def list_courses(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    client = get_supabase_client()
    course_result = (
        client.table("courses")
        .select("id,title,description,duration_minutes")
        .eq("active", True)
        .order("title")
        .execute()
    )
    courses = course_result.data or []
    assignments_result = (
        client.table("course_assignments")
        .select("course_id,status,progress_percent,score_percent,assigned_at,completed_at")
        .eq("employee_id", actor.id)
        .execute()
    )
    assignments = {row["course_id"]: row for row in assignments_result.data or []}
    return [{**course, "assignment": assignments.get(course["id"])} for course in courses]


@router.get("/my-courses")
def my_courses(actor: UserContext = Depends(get_current_user)) -> list[dict]:
    return get_assigned_courses(get_supabase_client(), actor.id)


@router.get("/courses/{course_id}")
def course_details(
    course_id: str,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    course = _get_course(course_id)
    assignment = _find_assignment(course_id, actor.id)
    if assignment is None and actor.role != "hr_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Course is not assigned to you")
    course["quiz"] = _public_quiz(course.get("quiz") or [])
    course["assignment"] = assignment
    return course


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def assign_course(
    payload: CourseAssignmentCreate,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    if actor.role not in ("manager", "director", "hr_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager, director or HR role required")
    employee = ensure_can_manage_employee(actor, payload.employee_id)
    _get_course(payload.course_id)
    if _find_assignment(payload.course_id, payload.employee_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Course is already assigned")

    result = (
        get_supabase_client()
        .table("course_assignments")
        .insert(
            {
                "course_id": payload.course_id,
                "employee_id": payload.employee_id,
                "assigned_by": actor.id,
            }
        )
        .execute()
    )
    assignment = (result.data or [None])[0]
    if assignment is None:
        raise HTTPException(status_code=500, detail="Course assignment failed")
    create_notification(
        str(employee["id"]),
        "Назначено обучение",
        "Вам назначен новый учебный курс Jana Academy.",
        "course_assigned",
    )
    return assignment


@router.patch("/courses/{course_id}/progress")
def update_progress(
    course_id: str,
    payload: CourseProgressUpdate,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    assignment = _find_assignment(course_id, actor.id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course assignment not found")
    if assignment["status"] == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Course is already completed")

    progress = max(int(assignment["progress_percent"]), payload.progress_percent)
    result = (
        get_supabase_client()
        .table("course_assignments")
        .update({"progress_percent": progress, "status": "in_progress" if progress else "not_started"})
        .eq("id", assignment["id"])
        .execute()
    )
    updated = (result.data or [None])[0]
    if updated is None:
        raise HTTPException(status_code=500, detail="Course progress could not be saved")
    return updated


@router.post("/courses/{course_id}/complete")
def complete_course(
    course_id: str,
    payload: QuizSubmission,
    actor: UserContext = Depends(get_current_user),
) -> dict:
    assignment = _find_assignment(course_id, actor.id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course assignment not found")
    course = _get_course(course_id)
    quiz = course.get("quiz") or []
    if not quiz:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This course has no configured quiz")

    question_ids = {str(question["id"]) for question in quiz}
    if set(payload.answers) != question_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Answer every quiz question exactly once")
    if any(
        answer_index < 0 or answer_index >= len(question.get("options", []))
        for question in quiz
        for answer_index in [payload.answers[str(question["id"])]]
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Quiz answer option is invalid")
    correct = sum(
        payload.answers[str(question["id"])] == int(question["answer_index"])
        for question in quiz
    )
    score = round(correct * 100 / len(quiz), 2)
    result = (
        get_supabase_client()
        .table("course_assignments")
        .update(
            {
                "status": "completed",
                "progress_percent": 100,
                "score_percent": score,
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", assignment["id"])
        .execute()
    )
    updated = (result.data or [None])[0]
    if updated is None:
        raise HTTPException(status_code=500, detail="Course result could not be saved")

    profile = get_profile(actor.id)
    if profile.get("manager_id"):
        create_notification(
            str(profile["manager_id"]),
            "Обучение завершено",
            f"{profile['full_name']} завершил(а) курс «{course['title']}» с результатом {score}%.",
            "course_completed",
        )
    return updated
