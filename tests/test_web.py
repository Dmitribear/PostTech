from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import mount_portal


def test_missing_build_keeps_api_only(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_portal(app, tmp_path) is False
    assert TestClient(app).get("/").status_code == 404


def test_portal_deep_links_assets_and_api_boundary(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>PostTech portal</html>", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('portal')", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/v1/health/live")
    def health() -> dict:
        return {"status": "alive"}

    assert mount_portal(app, tmp_path) is True
    client = TestClient(app)
    for path in ["/", "/requests/new", "/requests/test-id", "/academy", "/calendar"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
        assert "PostTech portal" in response.text
    assert client.get("/api/v1/health/live").json() == {"status": "alive"}
    for path in ["/api/v1/missing", "/api", "/assets/missing.js", "/docs/missing"]:
        assert client.get(path).status_code == 404
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg+xml")
    assert client.get("/docs").status_code == 200
