from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.bootstrap import configure_application
from app.domain.errors import ApplicationError, StorageError, StorageUnavailable
from app.domain.localization import locale
from app.presentation.http.router import api_router
from app.presentation.web import mount_portal

app = FastAPI(
    title="PostTech API",
    description="Digital HR MVP API for profiles, requests, learning, notifications, and Jana AI.",
    version="0.1.0",
)

configure_application()


@app.exception_handler(StorageError)
@app.exception_handler(StorageUnavailable)
async def storage_error_handler(request, error):
    return JSONResponse(
        status_code=503, content={"detail": "HR database is temporarily unavailable"}
    )


@app.exception_handler(ApplicationError)
async def application_error_handler(request, error: ApplicationError):
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": error.detail},
        headers=error.headers,
    )


app.include_router(api_router, prefix="/api/v1")


if not mount_portal(app, Path(__file__).resolve().parent.parent / "frontend" / "dist"):

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": "PostTech API", "docs": "/docs"}


@app.middleware("http")
async def content_locale(request, call_next):
    language = (
        request.headers.get("accept-language", "ru").split(",")[0].split("-")[0].lower()
    )
    token = locale.set("kk" if language in ("kk", "kz") else "ru")
    try:
        response = await call_next(request)
        response.headers["Content-Language"] = locale.get()
        response.headers["Vary"] = "Accept-Language"
        return response
    finally:
        locale.reset(token)
