"""Role-scoped academy reads and atomic commands implemented by SQL RPCs."""
from app.core.locale import course_content
import logging
from uuid import UUID, uuid4

from fastapi import HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.db.supabase import get_supabase_client
from app.schemas.common import UserContext

logger = logging.getLogger(__name__)
COURSE_COLUMNS = "id,title,description,duration_minutes,category,audience,passing_score,translations"
ASSIGNMENT_COLUMNS = (
    "id,course_id,employee_id,assigned_by,status,progress_percent,score_percent,"
    "assigned_at,completed_at,attempt_count,material_completed_at,last_attempt_at,due_on,completed_lesson_ids"
)
ATTEMPT_COLUMNS = "id,assignment_id,attempt_number,score_percent,passed,submitted_at"
EMPLOYEE_COLUMNS = "id,full_name,department,job_title"


def _client():
    try:
        return get_supabase_client()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="HR database is not configured") from exc


def _execute(query):
    try:
        return query.execute().data
    except APIError as exc:
        if exc.code in {"PT403", "PT404", "PT409", "PT422"}:
            raise HTTPException(status_code=int(exc.code[2:]), detail=exc.message) from exc
        if exc.code in {"PGRST202", "42P01", "42703"}:
            raise HTTPException(status_code=503, detail="Academy workflow is not installed; apply the database migrations") from exc
        logger.warning("Academy database operation failed (code=%s)", exc.code)
        raise HTTPException(status_code=503, detail="Academy is temporarily unavailable; retry later") from exc
    except HTTPError as exc:
        raise HTTPException(status_code=503, detail="Academy is temporarily unavailable; retry later") from exc


def _all_rows(build_query) -> list[dict]:
    """Avoid silently dropping assignments at the PostgREST default row limit."""
    result, offset = [], 0
    while True:
        rows = _execute(build_query().range(offset, offset + 199)) or []
        result.extend(rows)
        if len(rows) < 200:
            return result
        offset += len(rows)


def _assignment(actor: UserContext, course_id: UUID) -> dict:
    rows = _execute(_client().table("course_assignments").select(ASSIGNMENT_COLUMNS)
                    .eq("course_id", str(course_id)).eq("employee_id", actor.id).limit(1)) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Course assignment not found")
    return rows[0]


def list_courses(actor: UserContext) -> list[dict]:
    client = _client()
    courses = _all_rows(lambda: client.table("courses").select(COURSE_COLUMNS).eq("active", True).order("title").order("id"))
    assignments = _all_rows(lambda: client.table("course_assignments").select(ASSIGNMENT_COLUMNS).eq("employee_id", actor.id).order("id"))
    mapped = {str(row["course_id"]): row for row in assignments}
    return [{**course_content(course), "assignment": mapped.get(str(course["id"]))} for course in courses]


def my_courses(actor: UserContext) -> list[dict]:
    client = _client()
    assignments = _all_rows(lambda: client.table("course_assignments").select(ASSIGNMENT_COLUMNS).eq("employee_id", actor.id).order("assigned_at", desc=True).order("id"))
    if not assignments:
        return []
    courses = _all_rows(lambda: client.table("courses").select(COURSE_COLUMNS).order("id"))
    mapped = {str(row["id"]): course_content(row) for row in courses}
    return [{**assignment, "course": mapped.get(str(assignment["course_id"]))} for assignment in assignments]


def course_details(actor: UserContext, course_id: UUID) -> dict:
    client = _client()
    rows = _execute(client.table("courses").select(f"{COURSE_COLUMNS},material_markdown,quiz,active,created_at,lessons")
                    .eq("id", str(course_id)).limit(1)) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Course not found")
    assignments = _execute(client.table("course_assignments").select(ASSIGNMENT_COLUMNS)
                           .eq("course_id", str(course_id)).eq("employee_id", actor.id).limit(1)) or []
    assignment = assignments[0] if assignments else None
    if assignment is None and actor.role not in ("manager", "director", "hr_admin"):
        raise HTTPException(status_code=403, detail="Course is not assigned to you")
    course = course_content(rows[0])
    if not course["active"] and assignment is None:
        raise HTTPException(status_code=404, detail="Course not found")
    # Allowlist: future private answer explanations must not accidentally leak.
    quiz = [{key: question[key] for key in ("id", "prompt", "options") if key in question}
            for question in course.get("quiz") or []]
    return {**course, "quiz": quiz, "assignment": assignment}


def course_attempts(actor: UserContext, course_id: UUID) -> list[dict]:
    assignment = _assignment(actor, course_id)
    return _all_rows(lambda: _client().table("course_attempts").select(ATTEMPT_COLUMNS)
                     .eq("assignment_id", assignment["id"]).order("attempt_number", desc=True).order("id"))


def team_courses(actor: UserContext, employee_id: UUID | None, course_id: UUID | None) -> list[dict]:
    if actor.role not in ("manager", "director", "hr_admin"):
        raise HTTPException(status_code=403, detail="Manager or HR role required")
    client = _client()

    def people_query():
        query = client.table("employee_profiles").select(EMPLOYEE_COLUMNS)
        if actor.role in ("manager", "director"):
            query = query.eq("manager_id", actor.id)
        return query.order("full_name").order("id")

    employees = _all_rows(people_query)
    if employee_id is not None:
        employees = [row for row in employees if str(row["id"]) == str(employee_id)]
        if not employees:
            raise HTTPException(status_code=403, detail="You cannot manage this employee")
    if not employees:
        return []
    people = {str(row["id"]): row for row in employees}
    assignments = []
    ids = list(people)
    for start in range(0, len(ids), 100):
        batch_ids = ids[start:start + 100]

        def assignment_query():
            query = client.table("course_assignments").select(ASSIGNMENT_COLUMNS).in_("employee_id", batch_ids)
            if course_id is not None:
                query = query.eq("course_id", str(course_id))
            return query.order("assigned_at", desc=True).order("id")

        assignments.extend(_all_rows(assignment_query))
    courses = _all_rows(lambda: client.table("courses").select(COURSE_COLUMNS).order("id"))
    catalog = {str(row["id"]): course_content(row) for row in courses}
    return [{**row, "employee": people[str(row["employee_id"])], "course": catalog.get(str(row["course_id"]))}
            for row in sorted(assignments, key=lambda value: (value["assigned_at"], value["id"]), reverse=True)]


def _command(name: str, params: dict) -> dict:
    result = _execute(_client().rpc(name, params))
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="Unexpected academy workflow response")
    return result


def assign_course(actor: UserContext, employee_id: UUID, course_id: UUID, due_on=None) -> dict:
    if actor.role not in ("manager", "director", "hr_admin"):
        raise HTTPException(status_code=403, detail="Manager or HR role required")
    if due_on is not None:
        return _command("assign_academy_course_due", {"p_actor_id": actor.id, "p_employee_id": str(employee_id), "p_course_id": str(course_id), "p_due_on": due_on.isoformat()})
    return _command("assign_academy_course", {"p_actor_id": actor.id, "p_employee_id": str(employee_id), "p_course_id": str(course_id)})


def update_progress(actor: UserContext, course_id: UUID, progress: int) -> dict:
    return _command("update_academy_progress", {"p_actor_id": actor.id, "p_course_id": str(course_id), "p_progress_percent": progress})


def complete_course(actor: UserContext, course_id: UUID, answers: dict[str, int], key: UUID | None) -> dict:
    result = _command("submit_academy_quiz", {"p_actor_id": actor.id, "p_course_id": str(course_id),
                    "p_answers": answers, "p_submission_id": str(key or uuid4())})
    if result.get('status') == 'completed':
        try:
            _execute(_client().rpc('advance_learning_tracks', {'p_employee_id': actor.id}))
        except HTTPException:
            # Quiz completion is already committed; the idempotent worker retries.
            logger.warning('Next learning step deferred to workflow worker')
    return result
