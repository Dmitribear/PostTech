from app.application.ports import DataGateway


def get_assigned_courses(client: DataGateway, employee_id: str) -> list[dict]:
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
