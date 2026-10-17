import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from unittest.mock import MagicMock

from app.main import app
from app.api.routes import health
from app.schemas.digital_hr import RequestCreate
from app.services.jana import _rank_articles

client = TestClient(app)


def test_liveness_reports_alive() -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_ready_when_supabase_client_is_available(
    monkeypatch,
) -> None:
    database = MagicMock()
    monkeypatch.setattr(health, "get_supabase_client", lambda: database)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependency": "supabase"}
    database.table.return_value.select.return_value.limit.return_value.execute.assert_called_once()


def test_readiness_catches_database_outage_without_exposing_diagnostics(monkeypatch):
    database = MagicMock()
    database.table.return_value.select.return_value.limit.return_value.execute.side_effect = RuntimeError("private-provider-diagnostic")
    monkeypatch.setattr(health, "get_supabase_client", lambda: database)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "private-provider-diagnostic" not in response.text


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


def test_jana_retrieval_ranks_matching_hr_article() -> None:
    articles = [
        {
            "title": "Отпуск",
            "content": "Укажите даты отпуска в заявке и следите за статусом.",
            "keywords": ["отпуск", "заявка"],
        },
        {
            "title": "Обучение",
            "content": "Материалы доступны в Jana Academy.",
            "keywords": ["курс"],
        },
    ]

    ranked = _rank_articles("Как подать заявку на отпуск?", articles)

    assert [article["title"] for article in ranked] == ["Отпуск"]


def test_jana_retrieval_returns_no_source_for_unrelated_question() -> None:
    articles = [{"title": "Отпуск", "content": "Укажите даты отпуска.", "keywords": ["отпуск"]}]

    assert _rank_articles("Как сменить пароль от Wi-Fi?", articles) == []
