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

from app.core.locale import locale

@app.middleware("http")
async def content_locale(request, call_next):
    language=request.headers.get("accept-language", "ru").split(",")[0].split("-")[0].lower()
    token=locale.set("kk" if language in ("kk","kz") else "ru")
    try:
        response=await call_next(request)
        response.headers["Content-Language"]=locale.get()
        response.headers["Vary"]="Accept-Language"
        return response
    finally:
        locale.reset(token)
