"""Serve the built portal without exposing source files or changing API routing."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_portal(app: FastAPI, directory: Path) -> bool:
    index = directory / "index.html"
    if not index.is_file():
        return False

    assets = directory / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="portal-assets")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> FileResponse:
        icon = directory / "favicon.svg"
        if not icon.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(icon, media_type="image/svg+xml")

    @app.get("/", include_in_schema=False)
    def portal_root() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    @app.get("/{path:path}", include_in_schema=False)
    def portal_route(path: str) -> FileResponse:
        # Unknown API/asset URLs must stay 404s, not successful HTML responses.
        if path.split("/", 1)[0] in {"api", "assets", "docs", "redoc", "openapi.json"}:
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True
