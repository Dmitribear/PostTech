from fastapi import FastAPI

from app.api.router import api_router

app = FastAPI(
    title="PostTech API",
    description="Digital HR MVP API for profiles, requests, learning, notifications, and Jana AI.",
    version="0.1.0",
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": "PostTech API", "docs": "/docs"}
