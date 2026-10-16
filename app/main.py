from pathlib import Path

from fastapi import FastAPI

from app.api.router import api_router
from app.web import mount_portal

app = FastAPI(
    title="PostTech API",
    description="Digital HR MVP API for profiles, requests, learning, notifications, and Jana AI.",
    version="0.1.0",
)

app.include_router(api_router, prefix="/api/v1")


if not mount_portal(app, Path(__file__).resolve().parent.parent / "frontend" / "dist"):
    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": "PostTech API", "docs": "/docs"}
