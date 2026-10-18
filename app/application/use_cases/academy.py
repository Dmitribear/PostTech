"""Role-scoped academy reads and atomic commands implemented by SQL RPCs."""

import logging
from uuid import UUID, uuid4

from app.application.dependencies import get_data_gateway
from app.domain.errors import ApplicationError, StorageError, StorageUnavailable
from app.domain.localization import course_content
from app.domain.models import UserContext

logger = logging.getLogger(__name__)
COURSE_COLUMNS = "id,title,description,duration_minutes,category,audience,passing_score,translations,course_type,provider,external_url,owner_employee_id"
ASSIGNMENT_COLUMNS = (
    "id,course_id,employee_id,assigned_by,status,progress_percent,score_percent,"
    "assigned_at,completed_at,attempt_count,material_completed_at,last_attempt_at,due_on,completed_lesson_ids"
)
ATTEMPT_COLUMNS = "id,assignment_id,attempt_number,score_percent,passed,submitted_at"
EMPLOYEE_COLUMNS = "id,full_name,department,job_title"


def data_gateway():
    try:
        return get_data_gateway()
    except (RuntimeError, ValueError) as exc:
        raise ApplicationError(
            status_code=503, detail="HR database is not configured"
        ) from exc


def execute_query(query):
    try:
        return query.execute().data
    except StorageError as exc:
        if exc.code in {"PT403", "PT404", "PT409", "PT422"}:
            raise ApplicationError(
                status_code=int(exc.code[2:]), detail=exc.message
            ) from exc
        if exc.code in {"PGRST202", "42P01", "42703"}:
            raise ApplicationError(
                status_code=503,
                detail="Academy workflow is not installed; apply the database migrations",
            ) from exc
        logger.warning("Academy database operation failed (code=%s)", exc.code)
        raise ApplicationError(
            status_code=503, detail="Academy is temporarily unavailable; retry later"
        ) from exc
    except StorageUnavailable as exc:
        raise ApplicationError(
            status_code=503, detail="Academy is temporarily unavailable; retry later"
        ) from exc


def read_all_rows(build_query) -> list[dict]:
    """Avoid silently dropping assignments at the PostgREST default row limit."""
    result, offset = [], 0
    while True:
        rows = execute_query(build_query().range(offset, offset + 199)) or []
        result.extend(rows)
        if len(rows) < 200:
            return result
        offset += len(rows)


def _assignment(actor: UserContext, course_id: UUID) -> dict:
    rows = (
        execute_query(
            data_gateway()
            .table("course_assignments")
            .select(ASSIGNMENT_COLUMNS)
            .eq("course_id", str(course_id))
            .eq("employee_id", actor.id)
            .limit(1)
        )
        or []
    )
    if not rows:
        raise ApplicationError(status_code=404, detail="Course assignment not found")
    return rows[0]


def list_courses(actor: UserContext) -> list[dict]:
    client = data_gateway()
    courses = read_all_rows(
        lambda: (
            client.table("courses")
            .select(COURSE_COLUMNS)
            .eq("active", True)
            .order("title")
            .order("id")
        )
    )
    assignments = read_all_rows(
        lambda: (
            client.table("course_assignments")
            .select(ASSIGNMENT_COLUMNS)
            .eq("employee_id", actor.id)
            .order("id")
        )
    )
    mapped = {str(row["course_id"]): row for row in assignments}
    return [
        {**course_content(course), "assignment": mapped.get(str(course["id"]))}
        for course in courses
        if not course.get("owner_employee_id")
    ]


def my_courses(actor: UserContext) -> list[dict]:
    client = data_gateway()
    assignments = read_all_rows(
        lambda: (
            client.table("course_assignments")
            .select(ASSIGNMENT_COLUMNS)
            .eq("employee_id", actor.id)
            .order("assigned_at", desc=True)
            .order("id")
        )
    )
    if not assignments:
        return []
    courses = read_all_rows(
        lambda: client.table("courses").select(COURSE_COLUMNS).order("id")
    )
    mapped = {str(row["id"]): course_content(row) for row in courses}
    return [
        {**assignment, "course": mapped.get(str(assignment["course_id"]))}
        for assignment in assignments
    ]


def course_details(actor: UserContext, course_id: UUID) -> dict:
    client = data_gateway()
    rows = (
        execute_query(
            client.table("courses")
            .select(
                f"{COURSE_COLUMNS},material_markdown,quiz,active,created_at,lessons"
            )
            .eq("id", str(course_id))
            .limit(1)
        )
        or []
    )
    if not rows:
        raise ApplicationError(status_code=404, detail="Course not found")
    assignments = (
        execute_query(
            client.table("course_assignments")
            .select(ASSIGNMENT_COLUMNS)
            .eq("course_id", str(course_id))
            .eq("employee_id", actor.id)
            .limit(1)
        )
        or []
    )
    assignment = assignments[0] if assignments else None
    if rows[0].get("owner_employee_id") and assignment is None:
        if actor.role not in ("manager", "director", "hr_admin") or not team_courses(
            actor, None, course_id
        ):
            raise ApplicationError(status_code=404, detail="Course not found")
    if (
        assignment is None
        and actor.role not in ("manager", "director", "hr_admin")
        and rows[0].get("course_type") != "external"
    ):
        raise ApplicationError(status_code=403, detail="Course is not assigned to you")
    course = course_content(rows[0])
    if (
        not course["active"]
        and assignment is None
        and not (
            actor.role in ("manager", "director", "hr_admin")
            and team_courses(actor, None, course_id)
        )
    ):
        raise ApplicationError(status_code=404, detail="Course not found")
    # Allowlist: future private answer explanations must not accidentally leak.
    quiz = [
        {key: question[key] for key in ("id", "prompt", "options") if key in question}
        for question in course.get("quiz") or []
    ]
    return {**course, "quiz": quiz, "assignment": assignment}


def course_attempts(actor: UserContext, course_id: UUID) -> list[dict]:
    assignment = _assignment(actor, course_id)
    return read_all_rows(
        lambda: (
            data_gateway()
            .table("course_attempts")
            .select(ATTEMPT_COLUMNS)
            .eq("assignment_id", assignment["id"])
            .order("attempt_number", desc=True)
            .order("id")
        )
    )


def team_courses(
    actor: UserContext, employee_id: UUID | None, course_id: UUID | None
) -> list[dict]:
    if actor.role not in ("manager", "director", "hr_admin"):
        raise ApplicationError(status_code=403, detail="Manager or HR role required")
    client = data_gateway()

    def people_query():
        query = client.table("employee_profiles").select(EMPLOYEE_COLUMNS)
        if actor.role in ("manager", "director"):
            query = query.eq("manager_id", actor.id)
        return query.order("full_name").order("id")

    employees = read_all_rows(people_query)
    if employee_id is not None:
        employees = [row for row in employees if str(row["id"]) == str(employee_id)]
        if not employees:
            raise ApplicationError(
                status_code=403, detail="You cannot manage this employee"
            )
    if not employees:
        return []
    people = {str(row["id"]): row for row in employees}
    assignments = []
    ids = list(people)
    for start in range(0, len(ids), 100):
        batch_ids = ids[start : start + 100]

        def assignment_query():
            query = (
                client.table("course_assignments")
                .select(ASSIGNMENT_COLUMNS)
                .in_("employee_id", batch_ids)
            )
            if course_id is not None:
                query = query.eq("course_id", str(course_id))
            return query.order("assigned_at", desc=True).order("id")

        assignments.extend(read_all_rows(assignment_query))
    courses = read_all_rows(
        lambda: client.table("courses").select(COURSE_COLUMNS).order("id")
    )
    catalog = {str(row["id"]): course_content(row) for row in courses}
    return [
        {
            **row,
            "employee": people[str(row["employee_id"])],
            "course": catalog.get(str(row["course_id"])),
        }
        for row in sorted(
            assignments,
            key=lambda value: (value["assigned_at"], value["id"]),
            reverse=True,
        )
    ]


def execute_command(name: str, params: dict) -> dict:
    result = execute_query(data_gateway().rpc(name, params))
    if not isinstance(result, dict):
        raise ApplicationError(
            status_code=503, detail="Unexpected academy workflow response"
        )
    return result


def assign_course(
    actor: UserContext, employee_id: UUID, course_id: UUID, due_on=None
) -> dict:
    if actor.role not in ("manager", "director", "hr_admin"):
        raise ApplicationError(status_code=403, detail="Manager or HR role required")
    if due_on is not None:
        return execute_command(
            "assign_academy_course_due",
            {
                "p_actor_id": actor.id,
                "p_employee_id": str(employee_id),
                "p_course_id": str(course_id),
                "p_due_on": due_on.isoformat(),
            },
        )
    return execute_command(
        "assign_academy_course",
        {
            "p_actor_id": actor.id,
            "p_employee_id": str(employee_id),
            "p_course_id": str(course_id),
        },
    )


def update_progress(actor: UserContext, course_id: UUID, progress: int) -> dict:
    if progress == 100:
        rows = (
            execute_query(
                data_gateway()
                .table("courses")
                .select("course_type")
                .eq("id", str(course_id))
                .limit(1)
            )
            or []
        )
        if not rows or rows[0].get("course_type") != "external":
            raise ApplicationError(
                422, "Internal courses are completed by passing the quiz"
            )
    result = execute_command(
        "update_academy_progress",
        {
            "p_actor_id": actor.id,
            "p_course_id": str(course_id),
            "p_progress_percent": progress,
        },
    )
    if result.get("status") == "completed":
        try:
            execute_query(
                data_gateway().rpc(
                    "advance_learning_tracks", {"p_employee_id": actor.id}
                )
            )
        except ApplicationError:
            logger.warning("Next learning step deferred to workflow worker")
    return result


def enroll_external_course(actor: UserContext, course_id: UUID) -> dict:
    return execute_command(
        "enroll_external_course",
        {"p_actor_id": actor.id, "p_course_id": str(course_id)},
    )


def complete_course(
    actor: UserContext, course_id: UUID, answers: dict[str, int], key: UUID | None
) -> dict:
    result = execute_command(
        "submit_academy_quiz",
        {
            "p_actor_id": actor.id,
            "p_course_id": str(course_id),
            "p_answers": answers,
            "p_submission_id": str(key or uuid4()),
        },
    )
    if result.get("status") == "completed":
        try:
            execute_query(
                data_gateway().rpc(
                    "advance_learning_tracks", {"p_employee_id": actor.id}
                )
            )
        except ApplicationError:
            # The quiz is already committed. The idempotent worker repairs next steps.
            logger.warning("Next learning step deferred to workflow worker")
    return result
