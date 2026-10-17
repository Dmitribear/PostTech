from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.supabase import get_supabase_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def liveness() -> dict[str, str]:
    """Confirm that the API process is responding."""
    return {"status": "alive"}


@router.get("/ready", response_model=None)
def readiness() -> dict[str, str] | JSONResponse:
    """Read one public knowledge row to check connectivity and the current schema."""
    try:
        get_supabase_client().table("knowledge_articles").select("id,version,reviewed_at,review_due_at").limit(1).execute()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "dependency": "supabase"},
        )
    return {"status": "ready", "dependency": "supabase"}
