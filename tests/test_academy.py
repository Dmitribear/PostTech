from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import academy
from app.core import permissions
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext


class MemoryQuery:
    """Exercise ownership and conditional writes without contacting Supabase."""

    def __init__(self, database, table):
        self.database = database
        self.table = table
        self.filters = []
        self.changes = None

    def select(self, _columns):
        return self

    def eq(self, field, value):
        self.filters.append(lambda row: row.get(field) == value)
        return self

    def neq(self, field, value):
        self.filters.append(lambda row: row.get(field) != value)
        return self

    def limit(self, _count):
        return self

    def update(self, changes):
        self.changes = changes
        return self

    def execute(self):
        if self.changes is not None and self.database.before_write is not None:
            callback = self.database.before_write
            self.database.before_write = None
            callback()
        matched = [
            row for row in self.database.rows[self.table]
            if all(predicate(row) for predicate in self.filters)
        ]
        if self.changes is not None:
            for row in matched:
                row.update(self.changes)
        return SimpleNamespace(data=deepcopy(matched))


class MemoryDatabase:
    def __init__(self):
        self.before_write = None
        self.rows = {
            "course_assignments": [{
                "id": "assignment-1",
                "course_id": "course-1",
                "employee_id": "worker-1",
                "status": "in_progress",
                "progress_percent": 40,
                "score_percent": None,
                "completed_at": None,
            }],
            "courses": [{
                "id": "course-1",
                "active": True,
                "title": "Demo course",
                "material_markdown": "Read the course material.",
                "quiz": [
                    {"id": "q1", "prompt": "First", "options": ["A", "B"], "answer_index": 0},
                    {"id": "q2", "prompt": "Second", "options": ["A", "B"], "answer_index": 1},
                ],
            }],
            "employee_profiles": [
                {"id": "worker-1", "manager_id": "manager-1"},
                {"id": "outsider", "manager_id": "manager-2"},
            ],
        }

    def table(self, name):
        return MemoryQuery(self, name)

    @property
    def assignment(self):
        return self.rows["course_assignments"][0]


@pytest.fixture
def academy_api(monkeypatch):
    database = MemoryDatabase()
    actor = UserContext(id="worker-1", auth_user_id="auth-1", role="worker")
    monkeypatch.setattr(academy, "get_supabase_client", lambda: database)
    monkeypatch.setattr(permissions, "get_supabase_client", lambda: database)
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        with TestClient(app) as client:
            yield client, database, actor
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_completion_saves_progress_and_calculated_score(academy_api):
    client, database, _actor = academy_api

    response = client.post(
        "/api/v1/academy/courses/course-1/complete",
        json={"answers": {"q1": 0, "q2": 0}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["progress_percent"] == 100
    assert response.json()["score_percent"] == 50
    assert response.json()["completed_at"]
    assert database.assignment == response.json()


def test_repeat_completion_cannot_overwrite_result(academy_api):
    client, database, _actor = academy_api
    database.assignment.update(status="completed", progress_percent=100, score_percent=50)
    original = deepcopy(database.assignment)

    response = client.post(
        "/api/v1/academy/courses/course-1/complete",
        json={"answers": {"q1": 0, "q2": 1}},
    )

    assert response.status_code == 409
    assert database.assignment == original


def test_concurrent_completion_preserves_first_result(academy_api):
    client, database, _actor = academy_api
    database.before_write = lambda: database.assignment.update(
        status="completed", progress_percent=100, score_percent=50, completed_at="first-result"
    )

    response = client.post(
        "/api/v1/academy/courses/course-1/complete",
        json={"answers": {"q1": 0, "q2": 1}},
    )

    assert response.status_code == 409
    assert database.assignment["score_percent"] == 50
    assert database.assignment["completed_at"] == "first-result"


def test_progress_update_does_not_lower_saved_progress(academy_api):
    client, database, _actor = academy_api

    response = client.patch(
        "/api/v1/academy/courses/course-1/progress", json={"progress_percent": 20}
    )

    assert response.status_code == 200
    assert database.assignment["progress_percent"] == 40


@pytest.mark.parametrize("concurrent_status,concurrent_progress", [
    ("in_progress", 80),
    ("completed", 100),
])
def test_stale_progress_cannot_undo_concurrent_progress_or_completion(
    academy_api, concurrent_status, concurrent_progress
):
    client, database, _actor = academy_api
    database.before_write = lambda: database.assignment.update(
        status=concurrent_status, progress_percent=concurrent_progress
    )

    response = client.patch(
        "/api/v1/academy/courses/course-1/progress", json={"progress_percent": 60}
    )

    assert response.status_code == 409
    assert database.assignment["status"] == concurrent_status
    assert database.assignment["progress_percent"] == concurrent_progress


def test_course_details_hide_quiz_answers(academy_api):
    client, database, _actor = academy_api

    response = client.get("/api/v1/academy/courses/course-1")

    assert response.status_code == 200
    assert len(response.json()["quiz"]) == 2
    assert all("answer_index" not in question for question in response.json()["quiz"])
    assert database.rows["courses"][0]["quiz"][0]["answer_index"] == 0


@pytest.mark.parametrize("method,suffix,payload,expected_status", [
    ("GET", "", None, 403),
    ("PATCH", "/progress", {"progress_percent": 60}, 404),
    ("POST", "/complete", {"answers": {"q1": 0, "q2": 1}}, 404),
])
def test_worker_cannot_access_another_employees_assignment(
    academy_api, method, suffix, payload, expected_status
):
    client, database, actor = academy_api
    actor.id = "outsider"
    original = deepcopy(database.assignment)

    response = client.request(
        method, "/api/v1/academy/courses/course-1" + suffix, json=payload
    )

    assert response.status_code == expected_status
    assert database.assignment == original


@pytest.mark.parametrize("role,actor_id", [("worker", "worker-1"), ("manager", "manager-1")])
def test_course_assignment_rejects_worker_or_manager_outside_team(academy_api, role, actor_id):
    client, _database, actor = academy_api
    actor.role = role
    actor.id = actor_id

    response = client.post(
        "/api/v1/academy/assignments",
        json={"course_id": "course-1", "employee_id": "outsider"},
    )

    assert response.status_code == 403
