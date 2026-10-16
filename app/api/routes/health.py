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
    """Confirm that required Supabase configuration can create a client."""
    try:
        get_supabase_client()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "dependency": "supabase"},
        )
    return {"status": "ready", "dependency": "supabase"}
