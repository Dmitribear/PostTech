import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.api.routes import health
from app.schemas.digital_hr import RequestCreate

client = TestClient(app)


def test_liveness_reports_alive() -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_ready_when_supabase_client_is_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(health, "get_supabase_client", lambda: object())

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependency": "supabase"}


def test_readiness_reports_unavailable_when_supabase_setup_fails(
    monkeypatch,
) -> None:
    def fail_to_create_client() -> None:
        raise ValueError("missing configuration")

    monkeypatch.setattr(health, "get_supabase_client", fail_to_create_client)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "dependency": "supabase"}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/profile", None),
        ("GET", "/api/v1/requests", None),
        ("GET", "/api/v1/academy/courses", None),
        ("GET", "/api/v1/notifications", None),
        ("POST", "/api/v1/ai/ask", {"question": "Как подать заявку на отпуск?"}),
    ],
)
def test_hr_routes_require_authentication(method: str, path: str, payload: dict | None) -> None:
    response = client.request(method, path, json=payload)

    assert response.status_code == 401


def test_leave_request_requires_valid_date_range() -> None:
    with pytest.raises(ValidationError):
        RequestCreate(
            request_type="leave",
            start_date="2026-11-10",
            end_date="2026-11-09",
        )


def test_advance_request_requires_positive_amount() -> None:
    with pytest.raises(ValidationError):
        RequestCreate(request_type="advance", amount=0)
