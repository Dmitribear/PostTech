from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from app.services import requests as workflow
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext
from app.services.calendar_export import CalendarExportUnavailable, leave_calendar

LEAVE = {"id": "30000000-0000-4000-8000-000000000001", "employee_id": "employee",
         "request_type": "leave", "status": "approved", "start_date": "2026-11-10", "end_date": "2026-11-15"}
PATH = f"/api/v1/requests/{LEAVE['id']}/calendar.ics"


def test_ics_roundtrip_preserves_inclusive_last_day_and_stable_uid():
    raw = leave_calendar({**LEAVE, "comment": "private comment\r\nATTENDEE:evil@example.com"})
    event = Calendar.from_ical(raw).walk("VEVENT")[0]
    assert event.decoded("dtstart") == date(2026, 11, 10)
    assert event.decoded("dtend") == date(2026, 11, 16)
    assert event["uid"] == Calendar.from_ical(leave_calendar(LEAVE)).walk("VEVENT")[0]["uid"]
    assert event["class"] == "PRIVATE" and event["status"] == "CONFIRMED"
    assert str(event["summary"]) == "Отпуск — JanaPost"
    assert "private comment" not in raw.decode() and "ATTENDEE" not in raw.decode()
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
    assert raw.endswith(b"\r\n")


def test_one_day_leave_and_year_boundary():
    event = Calendar.from_ical(leave_calendar({**LEAVE, "start_date": "2026-12-31", "end_date": "2026-12-31"})).walk("VEVENT")[0]
    assert event.decoded("dtend") == date(2027, 1, 1)


@pytest.mark.parametrize("changes", [
    {"status": "pending"}, {"status": "rejected"}, {"status": "cancelled"}, {"request_type": "advance"},
    {"end_date": "2026-11-09"}, {"start_date": None}, {"end_date": "9999-12-31"},
])
def test_only_approved_leave_with_valid_dates_is_exported(changes):
    with pytest.raises(CalendarExportUnavailable):
        leave_calendar({**LEAVE, **changes})


@pytest.fixture
def client(monkeypatch):
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: UserContext(id="employee", auth_user_id="auth", role="worker")
    class Query:
        def select(self, *_): return self
        def eq(self, *_): return self
        def limit(self, *_): return self
        def execute(self): return SimpleNamespace(data=[LEAVE])
    monkeypatch.setattr(workflow, "get_supabase_client", lambda: SimpleNamespace(table=lambda _: Query()))
    monkeypatch.setattr(workflow, "_profile", lambda employee_id: {"id": "employee", "manager_id": "manager"})
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


def test_download_requires_authentication():
    with TestClient(app) as client:
        assert client.get(PATH).status_code == 401


def test_download_headers_and_file(client):
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith('.ics"')
    assert len(Calendar.from_ical(response.content).walk("VEVENT")) == 1
    assert client.get('/api/v1/requests/not-uuid/calendar.ics').status_code == 422


@pytest.mark.parametrize("role,actor_id,expected", [
    ("worker", "stranger", 403), ("manager", "unrelated-manager", 403),
    ("manager", "manager", 200), ("hr_admin", "hr", 200),
])
def test_same_profile_visibility_rules_apply_to_export(client, role, actor_id, expected):
    app.dependency_overrides[get_current_user] = lambda: UserContext(id=actor_id, auth_user_id="auth", role=role)
    assert client.get(PATH).status_code == expected


def test_pending_request_rejected_after_authorization(client, monkeypatch):
    monkeypatch.setattr(workflow, "_execute", lambda _: [{**LEAVE, "status": "pending"}])
    assert client.get(PATH).status_code == 409


def test_missing_request_and_storage_failure(client, monkeypatch):
    monkeypatch.setattr(workflow, "_execute", lambda _: [])
    assert client.get(PATH).status_code == 404
    def unavailable():
        raise RuntimeError("database credentials")
    monkeypatch.setattr(workflow, "get_supabase_client", unavailable)
    response = client.get(PATH)
    assert response.status_code == 503 and "credentials" not in response.text


def test_portal_demo_export_uses_requested_dates_and_is_explicitly_fictional():
    from examples.jana_local_demo import app as demo_app
    with TestClient(demo_app) as demo:
        payload = {"id": LEAVE["id"], "start_date": "2026-12-31", "end_date": "2026-12-31"}
        response = demo.post("/demo/leave.ics", json=payload)
        assert response.status_code == 200
        event = Calendar.from_ical(response.content).walk("VEVENT")[0]
        assert str(event["summary"]).startswith("Демо:")
        assert event.decoded("dtend") == date(2027, 1, 1)
        assert response.headers["cache-control"] == "no-store"
        assert demo.post("/demo/leave.ics", json={**payload, "end_date": "2026-12-30"}).status_code == 422
        assert demo.post("/demo/leave.ics", json={**payload, "comment": "private"}).status_code == 422
    # Public demo export must never become part of the production app.
    with TestClient(app) as production:
        assert production.post("/demo/leave.ics", json=payload).status_code in (404, 405)
        assert not any(getattr(route, "path", None) == "/demo/leave.ics" for route in app.routes)
