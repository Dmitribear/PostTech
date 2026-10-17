from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.routes import academy, notifications, profile
from app.core import permissions, security
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext
from app.services import notifications as notification_service


WORKER = "10000000-0000-4000-8000-000000000001"
MANAGER = "10000000-0000-4000-8000-000000000002"
OTHER_WORKER = "10000000-0000-4000-8000-000000000003"
COURSE = "20000000-0000-4000-8000-000000000001"
OTHER_COURSE = "20000000-0000-4000-8000-000000000002"
PRIVATE = "private-value-that-must-not-be-returned"


def _employee(employee_id, name, role="worker", manager_id=None):
    return {
        "id": employee_id,
        "auth_user_id": str(UUID(int=UUID(employee_id).int + 100)),
        "employee_code": f"DEMO-{employee_id[-4:]}",
        "full_name": name,
        "email": f"employee-{employee_id[-4:]}@example.test",
        "company": "Demo Company",
        "job_title": "Demo Job",
        "department": "Demo Department",
        "manager_id": manager_id,
        "hired_at": "2024-01-15",
        "vacation_days_remaining": 18.5,
        "role": role,
        "external_source": "mock-1c-zup",
        "created_at": "2026-01-01T09:00:00Z",
        "updated_at": "2026-10-01T10:00:00Z",
    }


def _course(course_id, title):
    return {
        "id": course_id,
        "title": title,
        "description": "Demo course description",
        "duration_minutes": 15,
        "material_markdown": "Training material",
        "quiz": [{"id": "q1", "prompt": "Question", "options": ["A", "B"], "answer_index": 1}],
        "active": True,
    }


def _assignment(employee_id, course_id, number=1, assigned_at="2026-10-01T10:00:00Z"):
    return {
        "id": str(UUID(int=3000 + number)),
        "employee_id": employee_id,
        "course_id": course_id,
        "status": "in_progress",
        "progress_percent": 40,
        "score_percent": None,
        "assigned_by": MANAGER,
        "assigned_at": assigned_at,
        "completed_at": None,
    }


def _notification(employee_id, number=1, created_at="2026-10-01T10:00:00Z"):
    return {
        "id": str(UUID(int=4000 + number)),
        "employee_id": employee_id,
        "request_id": None,
        "notification_type": "course_assigned",
        "title": f"Training notification {number}",
        "body": "A course was assigned.",
        "read_at": None,
        "created_at": created_at,
    }


class ReadQuery:
    """Read-only PostgREST subset; ownership filters run against mixed employee data."""

    def __init__(self, database, table_name):
        self.database = database
        self.table_name = table_name
        self.columns = "*"
        self.filters = []
        self.ordering = []
        self.row_limit = None

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, [value]))
        return self

    def in_(self, column, values):
        self.filters.append((column, list(values)))
        return self

    def order(self, column, desc=False):
        self.ordering.append((column, desc))
        return self

    def limit(self, value):
        self.row_limit = value
        return self

    def execute(self):
        self.database.queries.append(self)
        rows = [deepcopy(row) for row in self.database.tables[self.table_name]
                if all(row.get(column) in values for column, values in self.filters)]
        for column, descending in reversed(self.ordering):
            rows.sort(key=lambda row: row.get(column) or "", reverse=descending)
        if self.row_limit is not None:
            rows = rows[:self.row_limit]
        if self.columns != "*" and self.database.project_columns:
            columns = [column.strip() for column in self.columns.split(",")]
            rows = [{column: row[column] for column in columns if column in row} for row in rows]
        return SimpleNamespace(data=rows)


class ProfileDatabase:
    def __init__(self):
        self.project_columns = True
        self.queries = []
        self.tables = {
            "employee_profiles": [
                _employee(WORKER, "Demo Worker", manager_id=MANAGER),
                _employee(MANAGER, "Demo Manager", role="manager"),
                _employee(OTHER_WORKER, "Unrelated Worker"),
            ],
            "courses": [_course(COURSE, "Assigned course"), _course(OTHER_COURSE, "Other person's course")],
            "course_assignments": [
                _assignment(WORKER, COURSE),
                _assignment(OTHER_WORKER, OTHER_COURSE, 2),
            ],
            "notifications": [
                _notification(WORKER),
                _notification(OTHER_WORKER, 2, "2026-10-02T10:00:00Z"),
            ],
        }

    def table(self, table_name):
        return ReadQuery(self, table_name)


@pytest.fixture
def profile_client(monkeypatch):
    database = ProfileDatabase()
    provider = Mock(return_value=database)
    for module in (profile, permissions, academy, notifications, notification_service):
        monkeypatch.setattr(module, "get_supabase_client", provider)
    auth_provider = Mock(side_effect=AssertionError("Unexpected live Auth call"))
    monkeypatch.setattr(security, "get_supabase_client", auth_provider)
    current_actor = {"value": UserContext(
        id=WORKER, auth_user_id=database.tables["employee_profiles"][0]["auth_user_id"],
        role="worker", manager_id=MANAGER,
    )}
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: current_actor["value"]
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client, database=database, actor=current_actor,
                provider=provider, auth_provider=auth_provider,
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_profile_combines_hr_fields_manager_training_and_notifications(profile_client):
    before = deepcopy(profile_client.database.tables)
    response = profile_client.client.get("/api/v1/profile")

    assert response.status_code == 200
    body = response.json()
    expected_fields = {
        key: value for key, value in before["employee_profiles"][0].items() if key != "auth_user_id"
    }
    assert {key: body[key] for key in expected_fields} == expected_fields
    assert body["manager"] == {"id": MANAGER, "full_name": "Demo Manager"}
    assignment = body["assigned_courses"][0]
    assert assignment["id"] == before["course_assignments"][0]["id"]
    assert assignment["employee_id"] == WORKER
    assert assignment["progress_percent"] == 40
    assert assignment["course"] == {
        "id": COURSE, "title": "Assigned course", "description": "Demo course description", "duration_minutes": 15,
    }
    assert [item["employee_id"] for item in body["notifications"]] == [WORKER]
    assert profile_client.database.tables == before


@pytest.mark.parametrize("role", ["worker", "manager", "director", "hr_admin"])
def test_profile_always_uses_current_employee_even_if_query_names_someone_else(profile_client, role):
    profile_client.actor["value"] = profile_client.actor["value"].model_copy(update={"role": role})
    profile_client.database.tables["employee_profiles"][0]["role"] = role

    response = profile_client.client.get("/api/v1/profile", params={"employee_id": OTHER_WORKER})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == WORKER
    assert body["role"] == role
    assert {item["employee_id"] for item in body["assigned_courses"]} == {WORKER}
    assert {item["employee_id"] for item in body["notifications"]} == {WORKER}
    assert OTHER_COURSE not in response.text
    assert "Unrelated Worker" not in response.text


def test_worker_gets_manager_name_without_access_to_full_manager_profile(profile_client):
    own = profile_client.client.get("/api/v1/profile")
    manager = profile_client.client.get(f"/api/v1/employees/{MANAGER}")
    other = profile_client.client.get(f"/api/v1/employees/{OTHER_WORKER}")

    assert own.status_code == 200
    assert own.json()["manager"] == {"id": MANAGER, "full_name": "Demo Manager"}
    assert manager.status_code == 403
    assert other.status_code == 403
    assert "Demo Manager" not in manager.text


def test_profile_response_filters_unexpected_fields_at_every_level(profile_client):
    database = profile_client.database
    # Simulate an overbroad storage response to exercise the response model as
    # well as the normal restricted SELECT columns.
    database.project_columns = False
    for table in database.tables.values():
        for row in table:
            row["unexpected_internal_field"] = PRIVATE
    database.tables["employee_profiles"][1]["email"] = PRIVATE
    database.tables["courses"][0]["quiz"][0]["prompt"] = PRIVATE

    response = profile_client.client.get("/api/v1/profile")

    assert response.status_code == 200
    body = response.json()
    assert PRIVATE not in response.text
    assert "auth_user_id" not in response.text
    assert body["manager"] == {"id": MANAGER, "full_name": "Demo Manager"}
    assert set(body["assigned_courses"][0]["course"]) == {
        "id", "title", "description", "duration_minutes",
    }
    assert "quiz" not in body["assigned_courses"][0]["course"]


def test_profile_without_manager_training_or_notifications_returns_empty_sections(profile_client):
    database = profile_client.database
    database.tables["employee_profiles"][0]["manager_id"] = None
    database.tables["course_assignments"] = [
        row for row in database.tables["course_assignments"] if row["employee_id"] != WORKER
    ]
    database.tables["notifications"] = [
        row for row in database.tables["notifications"] if row["employee_id"] != WORKER
    ]

    response = profile_client.client.get("/api/v1/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["manager_id"] is None
    assert body["manager"] is None
    assert body["assigned_courses"] == []
    assert body["notifications"] == []


def test_profile_matches_existing_learning_and_notification_endpoints(profile_client):
    response = profile_client.client.get("/api/v1/profile")
    courses = profile_client.client.get("/api/v1/academy/my-courses")
    notices = profile_client.client.get("/api/v1/notifications")

    assert response.status_code == courses.status_code == notices.status_code == 200
    assert response.json()["assigned_courses"] == courses.json()
    assert response.json()["notifications"] == notices.json()


def test_profile_training_is_sorted_by_assignment_date(profile_client):
    profile_client.database.tables["course_assignments"].append(
        _assignment(WORKER, OTHER_COURSE, 3, "2026-10-05T10:00:00Z"),
    )

    response = profile_client.client.get("/api/v1/profile")

    assert response.status_code == 200
    assert [row["course_id"] for row in response.json()["assigned_courses"]] == [OTHER_COURSE, COURSE]


def test_profile_returns_latest_100_own_notifications_without_marking_them_read(profile_client):
    database = profile_client.database
    start = datetime(2026, 10, 1, tzinfo=UTC)
    notices = [
        _notification(WORKER, number, (start + timedelta(minutes=number)).isoformat().replace("+00:00", "Z"))
        for number in range(1, 106)
    ]
    database.tables["notifications"] = [
        _notification(OTHER_WORKER, 500, "2026-12-01T10:00:00Z"),
        *notices,
    ]
    before = deepcopy(database.tables["notifications"])

    response = profile_client.client.get("/api/v1/profile")

    assert response.status_code == 200
    result = response.json()["notifications"]
    assert len(result) == 100
    assert [row["id"] for row in result] == [row["id"] for row in reversed(notices[5:])]
    assert all(row["employee_id"] == WORKER and row["read_at"] is None for row in result)
    assert database.tables["notifications"] == before


def test_profile_remains_read_only(profile_client):
    response = profile_client.client.patch("/api/v1/profile", json={
        "full_name": "Changed", "role": "hr_admin", "vacation_days_remaining": 999,
    })
    assert response.status_code == 405
    profile_client.provider.assert_not_called()


def test_profile_requires_authentication_before_reading_storage(profile_client):
    app.dependency_overrides.pop(get_current_user)

    response = profile_client.client.get("/api/v1/profile")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    profile_client.provider.assert_not_called()
    profile_client.auth_provider.assert_not_called()


def test_profile_handles_missing_optional_audit_dates(profile_client):
    employee = profile_client.database.tables["employee_profiles"][0]
    employee.pop("created_at")
    employee.pop("updated_at")

    response = profile_client.client.get("/api/v1/profile")

    assert response.status_code == 200
    assert response.json()["created_at"] is None
    assert response.json()["updated_at"] is None
