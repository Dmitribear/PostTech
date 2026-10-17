from supabase import Client


def get_assigned_courses(client: Client, employee_id: str) -> list[dict]:
    """Load assignments for an employee already selected by an authorized route."""
    assignment_result = (
        client.table("course_assignments")
        .select("*")
        .eq("employee_id", employee_id)
        .order("assigned_at", desc=True)
        .execute()
    )
    assignments = assignment_result.data or []
    if not assignments:
        return []
    course_ids = list(dict.fromkeys(row["course_id"] for row in assignments))
    course_result = (
        client.table("courses")
        .select("id,title,description,duration_minutes")
        .in_("id", course_ids)
        .execute()
    )
    courses = {row["id"]: row for row in course_result.data or []}
    return [{**row, "course": courses.get(row["course_id"])} for row in assignments]
