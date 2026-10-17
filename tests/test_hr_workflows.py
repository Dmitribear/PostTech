from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.api.routes import academy, notifications, requests
from app.core import permissions
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext
from app.services import notifications as notification_service

WORKER = "worker-1"
OTHER_WORKER = "worker-2"
UNMANAGED_WORKER = "worker-unmanaged"
MANAGER = "manager-1"
OTHER_MANAGER = "manager-2"
HR = "hr-1"
DIRECTOR = "director-1"
COURSE = "course-1"


def actor(employee_id: str, role: str) -> UserContext:
    return UserContext(id=employee_id, auth_user_id=f"auth-{employee_id}", role=role)


def profile(employee_id: str, role: str, manager_id: str | None = None) -> dict:
    return {
        "id": employee_id,
        "auth_user_id": f"auth-{employee_id}",
        "employee_code": employee_id.upper(),
        "full_name": employee_id.replace("-", " ").title(),
        "email": f"{employee_id}@example.test",
        "company": "Demo Company",
        "job_title": "Demo role",
        "department": "Demo department",
        "manager_id": manager_id,
        "hired_at": "2024-01-01",
        "vacation_days_remaining": 20,
        "role": role,
    }


def request_row(request_id: str, employee_id: str, created_at: str) -> dict:
    start_date = date(2026, 11, 10)
    end_date = date(2026, 11, 12)
    return {
        "id": request_id,
        "employee_id": employee_id,
        "request_type": "leave",
        "status": "pending",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "leave_days": (end_date - start_date).days + 1,
        "amount": None,
        "comment": "",
        "reviewer_comment": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


def course_row() -> dict:
    return {
        "id": COURSE,
        "title": "Security basics",
        "description": "A short demo course",
        "duration_minutes": 15,
        "material_markdown": "## Read this material",
        "quiz": [
            {"id": "q1", "prompt": "First?", "options": ["A", "B"], "answer_index": 1},
            {"id": "q2", "prompt": "Second?", "options": ["A", "B"], "answer_index": 0},
        ],
        "active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def assignment_row(employee_id: str, assignment_id: str = "assignment-1") -> dict:
    return {
        "id": assignment_id,
        "course_id": COURSE,
        "employee_id": employee_id,
        "status": "in_progress",
        "progress_percent": 20,
        "score_percent": None,
        "assigned_by": MANAGER,
        "assigned_at": "2026-01-01T00:00:00+00:00",
        "completed_at": None,
    }


class MemoryQuery:
    """Small PostgREST-compatible subset for isolated route-level workflow tests."""

    def __init__(self, database: "MemorySupabase", table: str) -> None:
        self.database = database
        self.table_name = table
        self.columns = "*"
        self.filters: list[tuple[str, str, object]] = []
        self.ordering: tuple[str, bool] | None = None
        self.row_limit: int | None = None
        self.operation = "select"
        self.payload: dict | None = None

    def select(self, columns: str) -> "MemoryQuery":
        self.columns = columns
        return self

    def eq(self, column: str, value: object) -> "MemoryQuery":
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[object]) -> "MemoryQuery":
        self.filters.append(("in", column, values))
        return self

    def order(self, column: str, desc: bool = False) -> "MemoryQuery":
        self.ordering = (column, desc)
        return self

    def limit(self, count: int) -> "MemoryQuery":
        self.row_limit = count
        return self

    def insert(self, payload: dict) -> "MemoryQuery":
        self.operation = "insert"
        self.payload = deepcopy(payload)
        return self

    def update(self, payload: dict) -> "MemoryQuery":
        self.operation = "update"
        self.payload = deepcopy(payload)
        return self

    def _matches(self, row: dict) -> bool:
        for operator, column, value in self.filters:
            if operator == "eq" and row.get(column) != value:
                return False
            if operator == "in" and row.get(column) not in value:
                return False
        return True

    def execute(self) -> SimpleNamespace:
        rows = self.database.tables.setdefault(self.table_name, [])
        if self.operation == "insert":
            inserted = deepcopy(self.payload or {})
            self.database.next_id += 1
            inserted.setdefault("id", f"generated-{self.database.next_id}")
            if self.table_name == "hr_requests":
                inserted.setdefault("status", "pending")
                if inserted.get("request_type") == "leave":
                    start_date = date.fromisoformat(inserted["start_date"])
                    end_date = date.fromisoformat(inserted["end_date"])
                    inserted["leave_days"] = (end_date - start_date).days + 1
                inserted.setdefault("created_at", "2026-10-17T12:00:00+00:00")
                inserted.setdefault("updated_at", inserted["created_at"])
            elif self.table_name == "course_assignments":
                inserted.setdefault("status", "not_started")
                inserted.setdefault("progress_percent", 0)
                inserted.setdefault("score_percent", None)
                inserted.setdefault("assigned_at", "2026-10-17T12:00:00+00:00")
                inserted.setdefault("completed_at", None)
            elif self.table_name == "notifications":
                inserted.setdefault("read_at", None)
                inserted.setdefault("created_at", "2026-10-17T12:00:00+00:00")
            rows.append(inserted)
            return SimpleNamespace(data=[deepcopy(inserted)])

        matched = [row for row in rows if self._matches(row)]
        if self.operation == "update":
            for row in matched:
                if (
                    self.table_name == "hr_requests"
                    and row.get("status") != "approved"
                    and (self.payload or {}).get("status") == "approved"
                    and row.get("request_type") == "leave"
                ):
                    employee = next(
                        profile for profile in self.database.tables["employee_profiles"]
                        if profile["id"] == row["employee_id"]
                    )
                    if employee["vacation_days_remaining"] < row["leave_days"]:
                        raise APIError({"code": "PT413", "message": "Insufficient vacation balance"})
                    employee["vacation_days_remaining"] -= row["leave_days"]
                row.update(deepcopy(self.payload or {}))
            matched = [deepcopy(row) for row in matched]
        else:
            matched = [deepcopy(row) for row in matched]

        if self.ordering:
            column, descending = self.ordering
            matched.sort(key=lambda row: row.get(column) or "", reverse=descending)
        if self.row_limit is not None:
            matched = matched[: self.row_limit]
        if self.columns != "*":
            selected_columns = self.columns.split(",")
            matched = [
                {column: row[column] for column in selected_columns if column in row}
                for row in matched
            ]
        return SimpleNamespace(data=matched)


class MemorySupabase:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = deepcopy(tables)
        self.next_id = 0

    def table(self, table_name: str) -> MemoryQuery:
        return MemoryQuery(self, table_name)


@pytest.fixture
def workflow_client(monkeypatch):
    database = MemorySupabase(
        {
            "employee_profiles": [
                profile(WORKER, "worker", MANAGER),
                profile(OTHER_WORKER, "worker", OTHER_MANAGER),
                profile(UNMANAGED_WORKER, "worker"),
                profile(MANAGER, "manager"),
                profile(OTHER_MANAGER, "manager"),
                profile(HR, "hr_admin"),
            ],
            "hr_requests": [
                request_row("request-1", WORKER, "2026-10-17T11:00:00+00:00"),
                request_row("request-2", OTHER_WORKER, "2026-10-17T10:00:00+00:00"),
            ],
            "notifications": [],
            "courses": [course_row()],
            "course_assignments": [assignment_row(WORKER)],
        }
    )
    for module in (requests, academy, notifications, permissions, notification_service):
        monkeypatch.setattr(module, "get_supabase_client", lambda: database)

    current_actor = {"value": actor(WORKER, "worker")}
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: current_actor["value"]
    try:
        with TestClient(app) as client:
            yield client, database, current_actor
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_request_lists_are_scoped_by_worker_manager_and_hr(workflow_client):
    client, _, current_actor = workflow_client
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["request-1"]

    current_actor["value"] = actor(MANAGER, "manager")
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {"request-1"}

    current_actor["value"] = actor(HR, "hr_admin")
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {"request-1", "request-2"}


def test_worker_cannot_list_another_employee_requests(workflow_client):
    client, _, _ = workflow_client
    response = client.get(f"/api/v1/requests?employee_id={OTHER_WORKER}")
    assert response.status_code == 403


def test_creating_leave_request_sets_pending_and_notifies_manager(workflow_client):
    client, database, _ = workflow_client
    response = client.post(
        "/api/v1/requests",
        json={
            "request_type": "leave",
            "start_date": "2026-12-01",
            "end_date": "2026-12-05",
            "comment": "Family trip",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["employee_id"] == WORKER
    assert created["status"] == "pending"
    assert created["start_date"] == "2026-12-01"
    assert created["end_date"] == "2026-12-05"
    assert created["leave_days"] == 5
    manager_notifications = [item for item in database.tables["notifications"] if item["employee_id"] == MANAGER]
    assert len(manager_notifications) == 1
    assert manager_notifications[0]["notification_type"] == "request_created"
    assert manager_notifications[0]["request_id"] == created["id"]


def test_unassigned_employee_request_notifies_hr(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(UNMANAGED_WORKER, "worker")
    response = client.post("/api/v1/requests", json={"request_type": "advance", "amount": 2500})
    assert response.status_code == 201
    hr_notifications = [item for item in database.tables["notifications"] if item["employee_id"] == HR]
    assert len(hr_notifications) == 1
    assert hr_notifications[0]["notification_type"] == "request_created"
    assert hr_notifications[0]["request_id"] == response.json()["id"]


def test_worker_cannot_review_request(workflow_client):
    client, _, _ = workflow_client
    response = client.patch("/api/v1/requests/request-1/review", json={"status": "approved"})
    assert response.status_code == 403


def test_manager_can_review_direct_report_and_employee_is_notified(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    response = client.patch(
        "/api/v1/requests/request-1/review",
        json={"status": "approved", "reviewer_comment": "Approved"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending_hr"
    assert response.json()["manager_reviewed_by"] == MANAGER
    assert response.json()["manager_reviewer_comment"] == "Approved"
    assert next(item for item in database.tables["employee_profiles"] if item["id"] == WORKER)["vacation_days_remaining"] == 20
    employee_notifications = [item for item in database.tables["notifications"] if item["employee_id"] == WORKER]
    assert len(employee_notifications) == 1
    assert employee_notifications[0]["notification_type"] == "request_pending_hr"
    assert employee_notifications[0]["request_id"] == "request-1"
    hr_notifications = [item for item in database.tables["notifications"] if item["employee_id"] == HR]
    assert len(hr_notifications) == 1
    assert hr_notifications[0]["notification_type"] == "request_pending_hr"
    repeated_review = client.patch("/api/v1/requests/request-1/review", json={"status": "rejected"})
    assert repeated_review.status_code == 409


def test_manager_cannot_review_unrelated_employee_and_hr_cannot_bypass_manager(workflow_client):
    client, _, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    denied = client.patch("/api/v1/requests/request-2/review", json={"status": "rejected"})
    assert denied.status_code == 403
    current_actor["value"] = actor(HR, "hr_admin")
    premature = client.patch("/api/v1/requests/request-2/review", json={"status": "rejected"})
    assert premature.status_code == 409


def test_worker_request_goes_to_manager_then_hr_even_if_manager_reports_to_director(workflow_client):
    client, database, current_actor = workflow_client
    database.tables["employee_profiles"].append(profile(DIRECTOR, "director"))
    database.tables["employee_profiles"] = [
        {**item, "manager_id": DIRECTOR} if item["id"] == MANAGER else item
        for item in database.tables["employee_profiles"]
    ]

    current_actor["value"] = actor(MANAGER, "manager")
    manager_decision = client.patch(
        "/api/v1/requests/request-1/review",
        json={"status": "approved", "reviewer_comment": "Одобрено руководителем"},
    )
    assert manager_decision.status_code == 200
    assert manager_decision.json()["status"] == "pending_hr"
    assert manager_decision.json()["manager_reviewed_by"] == MANAGER
    assert not any(item["notification_type"] == "request_pending_director" for item in database.tables["notifications"])

    current_actor["value"] = actor(DIRECTOR, "director")
    director_inbox = client.get("/api/v1/requests")
    assert director_inbox.status_code == 200
    assert "request-1" not in {item["id"] for item in director_inbox.json()}
    director_cannot_review_worker_request = client.patch(
        "/api/v1/requests/request-1/review",
        json={"status": "approved"},
    )
    assert director_cannot_review_worker_request.status_code == 403

    current_actor["value"] = actor(HR, "hr_admin")
    hr_decision = client.patch(
        "/api/v1/requests/request-1/review",
        json={"status": "approved", "reviewer_comment": "Финальное решение HR"},
    )
    assert hr_decision.status_code == 200
    assert hr_decision.json()["status"] == "approved"
    assert hr_decision.json()["hr_reviewed_by"] == HR


def test_director_cannot_review_worker_request_or_another_managers_branch(workflow_client):
    client, database, current_actor = workflow_client
    database.tables["employee_profiles"].append(profile(DIRECTOR, "director"))
    database.tables["employee_profiles"] = [
        {**item, "manager_id": DIRECTOR} if item["id"] == MANAGER else item
        for item in database.tables["employee_profiles"]
    ]
    current_actor["value"] = actor(DIRECTOR, "director")
    premature = client.patch(
        "/api/v1/requests/request-1/review", json={"status": "approved"}
    )
    unrelated = client.patch(
        "/api/v1/requests/request-2/review", json={"status": "approved"}
    )
    assert premature.status_code == 403
    assert unrelated.status_code == 403


@pytest.mark.parametrize("final_status", ["approved", "rejected"])
def test_hr_makes_final_decision_after_manager_approval(workflow_client, final_status):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    manager_response = client.patch(
        "/api/v1/requests/request-1/review",
        json={"status": "approved", "reviewer_comment": "Manager approved"},
    )
    assert manager_response.status_code == 200
    assert manager_response.json()["status"] == "pending_hr"

    current_actor["value"] = actor(HR, "hr_admin")
    hr_response = client.patch(
        "/api/v1/requests/request-1/review",
        json={"status": final_status, "reviewer_comment": "HR decision"},
    )
    assert hr_response.status_code == 200
    result = hr_response.json()
    assert result["status"] == final_status
    assert result["manager_reviewed_by"] == MANAGER
    assert result["manager_reviewer_comment"] == "Manager approved"
    assert result["hr_reviewed_by"] == HR
    assert result["hr_reviewer_comment"] == "HR decision"
    assert result["reviewed_by"] == HR
    worker_balance = next(item for item in database.tables["employee_profiles"] if item["id"] == WORKER)["vacation_days_remaining"]
    assert worker_balance == (17 if final_status == "approved" else 20)
    employee_notifications = [item for item in database.tables["notifications"] if item["employee_id"] == WORKER]
    assert [item["notification_type"] for item in employee_notifications] == [
        "request_pending_hr",
        "request_status_changed",
    ]


def test_manager_rejection_is_final_without_hr_handoff(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    response = client.patch(
        "/api/v1/requests/request-1/review",
        json={"status": "rejected", "reviewer_comment": "Please reschedule"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["manager_reviewed_by"] == MANAGER
    assert response.json()["reviewed_by"] == MANAGER
    assert not any(item["employee_id"] == HR for item in database.tables["notifications"])


def test_hr_can_review_request_directly_when_employee_has_no_manager(workflow_client):
    client, _, current_actor = workflow_client
    current_actor["value"] = actor(UNMANAGED_WORKER, "worker")
    response = client.post(
        "/api/v1/requests",
        json={"request_type": "advance", "amount": 2500},
    )
    assert response.status_code == 201
    request_id = response.json()["id"]

    current_actor["value"] = actor(HR, "hr_admin")
    reviewed = client.patch(
        f"/api/v1/requests/{request_id}/review",
        json={"status": "approved", "reviewer_comment": "Reviewed by HR"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "approved"
    assert reviewed.json()["hr_reviewed_by"] == HR


def test_hr_cannot_approve_leave_exceeding_balance(workflow_client):
    client, database, current_actor = workflow_client
    worker = next(item for item in database.tables["employee_profiles"] if item["id"] == WORKER)
    worker["vacation_days_remaining"] = 2
    current_actor["value"] = actor(MANAGER, "manager")
    manager_decision = client.patch(
        "/api/v1/requests/request-1/review", json={"status": "approved"}
    )
    assert manager_decision.status_code == 200

    current_actor["value"] = actor(HR, "hr_admin")
    hr_decision = client.patch(
        "/api/v1/requests/request-1/review", json={"status": "approved"}
    )
    assert hr_decision.status_code == 409
    assert "Недостаточно дней отпуска" in hr_decision.json()["detail"]
    assert database.tables["hr_requests"][0]["status"] == "pending_hr"
    assert worker["vacation_days_remaining"] == 2


def test_manager_leave_request_goes_to_director_then_hr(workflow_client):
    client, database, current_actor = workflow_client
    director_id = DIRECTOR
    database.tables["employee_profiles"].append(profile(director_id, "director"))
    database.tables["employee_profiles"] = [
        {**item, "manager_id": director_id} if item["id"] == MANAGER else item
        for item in database.tables["employee_profiles"]
    ]

    # The manager submits their own leave request. The direct-manager relation
    # routes it to the director even though the requester also has role=manager.
    current_actor["value"] = actor(MANAGER, "manager")
    submitted = client.post(
        "/api/v1/requests",
        json={
            "request_type": "leave",
            "start_date": "2026-12-10",
            "end_date": "2026-12-15",
            "comment": "Отпуск руководителя",
        },
    )
    assert submitted.status_code == 201
    request_id = submitted.json()["id"]
    assert submitted.json()["employee_id"] == MANAGER
    assert any(
        item["employee_id"] == director_id
        and item["notification_type"] == "request_created"
        and item["request_id"] == request_id
        for item in database.tables["notifications"]
    )

    current_actor["value"] = actor(director_id, "director")
    director_requests = client.get("/api/v1/requests")
    assert director_requests.status_code == 200
    assert request_id in {item["id"] for item in director_requests.json()}
    director_decision = client.patch(
        f"/api/v1/requests/{request_id}/review",
        json={"status": "approved", "reviewer_comment": "Одобрено директором"},
    )
    assert director_decision.status_code == 200
    assert director_decision.json()["status"] == "pending_hr"
    assert director_decision.json()["director_reviewed_by"] == director_id

    current_actor["value"] = actor(HR, "hr_admin")
    hr_decision = client.patch(
        f"/api/v1/requests/{request_id}/review",
        json={"status": "approved", "reviewer_comment": "Финально согласовано HR"},
    )
    assert hr_decision.status_code == 200
    assert hr_decision.json()["status"] == "approved"
    assert hr_decision.json()["hr_reviewed_by"] == HR
    manager_balance = next(item for item in database.tables["employee_profiles"] if item["id"] == MANAGER)["vacation_days_remaining"]
    assert manager_balance == 14


def test_only_manager_or_hr_can_assign_courses_and_assignment_notifies_employee(workflow_client):
    client, database, current_actor = workflow_client
    database.tables["course_assignments"] = []
    payload = {"employee_id": WORKER, "course_id": COURSE}
    assert client.post("/api/v1/academy/assignments", json=payload).status_code == 403

    current_actor["value"] = actor(MANAGER, "manager")
    unrelated = client.post(
        "/api/v1/academy/assignments",
        json={"employee_id": OTHER_WORKER, "course_id": COURSE},
    )
    assert unrelated.status_code == 403

    response = client.post("/api/v1/academy/assignments", json=payload)
    assert response.status_code == 201
    assignment = response.json()
    assert assignment["employee_id"] == WORKER
    assert assignment["course_id"] == COURSE
    assert assignment["assigned_by"] == MANAGER
    assert assignment["status"] == "not_started"
    assert any(
        item["employee_id"] == WORKER and item["notification_type"] == "course_assigned"
        for item in database.tables["notifications"]
    )
    assert client.post("/api/v1/academy/assignments", json=payload).status_code == 409


def test_hr_can_assign_course_outside_manager_team(workflow_client):
    client, _, current_actor = workflow_client
    current_actor["value"] = actor(HR, "hr_admin")
    response = client.post(
        "/api/v1/academy/assignments",
        json={"employee_id": OTHER_WORKER, "course_id": COURSE},
    )
    assert response.status_code == 201


def test_course_material_is_only_visible_when_assigned_or_hr(workflow_client):
    client, _, current_actor = workflow_client
    response = client.get(f"/api/v1/academy/courses/{COURSE}")
    assert response.status_code == 200
    course = response.json()
    assert course["material_markdown"] == "## Read this material"
    assert course["assignment"]["employee_id"] == WORKER
    assert all("answer_index" not in question for question in course["quiz"])

    current_actor["value"] = actor(OTHER_WORKER, "worker")
    assert client.get(f"/api/v1/academy/courses/{COURSE}").status_code == 403
    current_actor["value"] = actor(HR, "hr_admin")
    assert client.get(f"/api/v1/academy/courses/{COURSE}").status_code == 200


def test_progress_never_decreases_and_completed_course_is_locked(workflow_client):
    client, database, _ = workflow_client
    response = client.patch(f"/api/v1/academy/courses/{COURSE}/progress", json={"progress_percent": 5})
    assert response.status_code == 200
    assert response.json()["progress_percent"] == 20
    assert response.json()["status"] == "in_progress"

    database.tables["course_assignments"][0]["status"] = "completed"
    response = client.patch(f"/api/v1/academy/courses/{COURSE}/progress", json={"progress_percent": 50})
    assert response.status_code == 409


def test_course_completion_saves_score_and_notifies_manager(workflow_client):
    client, database, _ = workflow_client
    response = client.post(
        f"/api/v1/academy/courses/{COURSE}/complete",
        json={"answers": {"q1": 1, "q2": 0}},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed"
    assert result["progress_percent"] == 100
    assert result["score_percent"] == 100
    assert result["completed_at"]
    manager_notifications = [
        item for item in database.tables["notifications"]
        if item["employee_id"] == MANAGER and item["notification_type"] == "course_completed"
    ]
    assert len(manager_notifications) == 1
    employee_notifications = [
        item for item in database.tables["notifications"]
        if item["employee_id"] == WORKER and item["notification_type"] == "course_completed"
    ]
    assert len(employee_notifications) == 1
    assert "100%" in employee_notifications[0]["body"]

    repeated = client.post(
        f"/api/v1/academy/courses/{COURSE}/complete",
        json={"answers": {"q1": 1, "q2": 0}},
    )
    assert repeated.status_code == 409
    assert len([
        item for item in database.tables["notifications"]
        if item["notification_type"] == "course_completed"
    ]) == 2


@pytest.mark.parametrize("answers", [{"q1": 1}, {"q1": 1, "q2": 0, "q3": 1}, {"q1": 5, "q2": 0}])
def test_course_completion_rejects_incomplete_or_invalid_answers(workflow_client, answers):
    client, _, _ = workflow_client
    response = client.post(f"/api/v1/academy/courses/{COURSE}/complete", json={"answers": answers})
    assert response.status_code == 422


def test_notifications_are_private_and_only_owner_can_mark_read(workflow_client):
    client, database, _ = workflow_client
    database.tables["notifications"] = [
        {"id": "notification-1", "employee_id": WORKER, "title": "Own", "read_at": None,
         "created_at": "2026-10-17T11:00:00+00:00"},
        {"id": "notification-2", "employee_id": OTHER_WORKER, "title": "Other", "read_at": None,
         "created_at": "2026-10-17T10:00:00+00:00"},
    ]
    response = client.get("/api/v1/notifications")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["notification-1"]

    assert client.post("/api/v1/notifications/notification-2/read").status_code == 404
    response = client.post("/api/v1/notifications/notification-1/read")
    assert response.status_code == 200
    assert response.json()["read_at"]