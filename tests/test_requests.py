from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import requests
from app.core import permissions
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext


@pytest.fixture
def request_api(monkeypatch):
    actor = UserContext(id="worker", auth_user_id="auth-worker", role="worker")
    profile = {"id": "worker", "manager_id": "manager"}
    record = {"id": "request", "employee_id": "worker", "status": "pending"}
    monkeypatch.setattr(requests, "_get_request", lambda _id: record.copy())
    monkeypatch.setattr(requests, "get_profile", lambda _id: profile.copy())
    monkeypatch.setattr(permissions, "get_profile", lambda _id: profile.copy())
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        with TestClient(app) as client:
            yield client, actor
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class ResultQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.payload = None

    def select(self, _columns):
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def order(self, _field):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


def test_create_request_has_no_fallible_side_effect_after_commit(request_api, monkeypatch):
    client, _actor = request_api
    query = ResultQuery([{"id": "created", "employee_id": "worker", "status": "pending"}])
    tables = []

    def table(name):
        tables.append(name)
        assert name == "hr_requests"
        return query

    def unexpected_profile_read(_id):
        raise RuntimeError("A failure after commit would create a misleading HTTP 500")

    monkeypatch.setattr(requests, "get_supabase_client", lambda: SimpleNamespace(table=table))
    monkeypatch.setattr(requests, "get_profile", unexpected_profile_read)
    response = client.post("/api/v1/requests", json={
        "request_type": "advance", "amount": 1000, "employee_id": "outsider",
    })

    assert response.status_code == 201
    assert query.payload["employee_id"] == "worker"
    assert tables == ["hr_requests"]


@pytest.mark.parametrize("role,actor_id", [
    ("worker", "worker"), ("manager", "manager"), ("hr_admin", "hr"),
])
def test_history_is_available_to_owner_manager_and_hr(request_api, monkeypatch, role, actor_id):
    client, actor = request_api
    actor.role, actor.id = role, actor_id
    history = [{"event_type": "created", "new_status": "pending"}]
    query = ResultQuery(history)
    monkeypatch.setattr(requests, "get_supabase_client", lambda: SimpleNamespace(table=lambda _: query))

    response = client.get("/api/v1/requests/request/history")

    assert response.status_code == 200
    assert response.json() == history
    assert query.filters == [("request_id", "request")]


@pytest.mark.parametrize("role", ["worker", "manager"])
def test_history_for_another_team_is_denied_before_query(request_api, monkeypatch, role):
    client, actor = request_api
    actor.role, actor.id = role, "outsider"

    def unexpected_database_access():
        pytest.fail("Forbidden request history must not be queried")

    monkeypatch.setattr(requests, "get_supabase_client", unexpected_database_access)
    assert client.get("/api/v1/requests/request/history").status_code == 403


def test_review_conflict_does_not_overwrite_a_concurrent_decision(request_api, monkeypatch):
    client, actor = request_api
    actor.role, actor.id = "manager", "manager"
    query = ResultQuery([])
    monkeypatch.setattr(requests, "get_supabase_client", lambda: SimpleNamespace(table=lambda _: query))

    response = client.patch("/api/v1/requests/request/review", json={"status": "approved"})

    assert response.status_code == 409
    assert ("status", "pending") in query.filters


def test_history_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/api/v1/requests/request/history").status_code == 401
