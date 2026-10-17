from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.infrastructure.database.client import get_supabase_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready", response_model=None)
def readiness() -> dict[str, str] | JSONResponse:
    """Check required extension columns too; an old schema must not appear ready."""
    try:
        client = get_supabase_client()
        for table, columns in (
            (
                "knowledge_articles",
                "id,version,reviewed_at,review_due_at,revision,draft",
            ),
            ("courses", "id,lessons"),
            ("course_assignments", "id,completed_lesson_ids"),
            ("leave_holds", "request_id,state"),
            ("integration_outbox", "id,status"),
            ("request_fulfillment", "request_id,status"),
            ("learning_enrollments", "id,track_id"),
            ("workflow_policy", "id,last_run_at"),
            ("employee_imports", "id,applied_at"),
            ("employee_role_changes", "id,employee_id,new_role"),
        ):
            client.table(table).select(columns).limit(1).execute()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "dependency": "supabase"},
        )
    return {"status": "ready", "dependency": "supabase"}
