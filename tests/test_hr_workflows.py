"""Main-branch HR regression scenarios against the integrated SQL workflow.

Only the verified identity and PostgREST transport are substituted. Request
transitions, role checks, balances, Academy scores and notifications execute the
real migrations in a disposable loopback PostgreSQL database, never Supabase.
"""
from datetime import date, timedelta
import re
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

psycopg = pytest.importorskip("psycopg", reason="Install tests/requirements-db.txt")
from psycopg import sql
from psycopg.types.json import Jsonb

from app.api.routes import notifications
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext
from app.services import academy, requests
from test_request_workflow_db import DATABASE_URL, create_request
from test_team_workflow_db import team_db
from test_team_http_db import SqlTable, execute

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Set a local POSTTECH_TEST_DATABASE_URL")


def stable_id(name):
    return str(uuid5(NAMESPACE_URL, "posttech-main-workflow-test/" + name))


WORKER, OTHER_WORKER, UNMANAGED_WORKER, MANAGER, OTHER_MANAGER, HR, DIRECTOR, COURSE = (
    stable_id(name) for name in
    ("worker", "other-worker", "unmanaged-worker", "manager", "other-manager", "hr", "director", "course")
)


def actor(employee_id, role):
    return UserContext(id=employee_id, auth_user_id=employee_id, role=role)


def rows(database, table):
    with database.connect() as connection:
        return [row[0] for row in connection.execute(
            sql.SQL("SELECT to_jsonb(t) FROM public.{} t ORDER BY id").format(sql.Identifier(table))
        )]


def request_id(database, owner=WORKER):
    return database.initial_requests[owner]


def request_path(database, owner=WORKER):
    return f"/api/v1/requests/{request_id(database, owner)}/review"


def leave_payload(offset=60, days=5):
    start = date.today() + timedelta(days=offset)
    return {"request_type": "leave", "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=days - 1)).isoformat(), "comment": "Family trip"}


class WorkflowTable(SqlTable):
    """Translate the route's actual filters to parameterized SQL, without business logic."""

    def __init__(self, database, name):
        assert name in {"hr_requests", "request_events", "employee_profiles", "notifications",
                        "courses", "course_assignments", "course_attempts"}
        self.database, self.name = database, name
        self.columns, self.filters, self.values, self.orders = [], [], [], []
        self.bounds, self.changes = None, None

    def select(self, columns):
        if columns == "*":
            self.columns = ["*"]
            return self
        return super().select(columns)

    def neq(self, column, value):
        self.filters.append(sql.SQL("{} <> %s").format(sql.Identifier(column)))
        self.values.append(value)
        return self

    def in_(self, column, values):
        self.filters.append(sql.SQL("{} = ANY(%s::uuid[])").format(sql.Identifier(column)))
        self.values.append(values)
        return self

    def is_(self, column, value):
        assert value == "null"
        self.filters.append(sql.SQL("{} IS NULL").format(sql.Identifier(column)))
        return self

    def or_(self, expression):
        # These scenarios have no active delegation; enforce the emitted
        # employee/approver/reviewer predicates rather than bypassing them.
        terms = []
        for item in expression.split(","):
            match = re.fullmatch(r"(employee_id|approver_ids|reviewed_by|manager_reviewed_by|director_reviewed_by)\.(eq|cs)\.\{?([0-9a-f-]{36})\}?", item)
            assert match, f"Unsupported PostgREST predicate: {item}"
            column, operator, value = match.groups()
            if operator == "cs":
                assert column == "approver_ids"
                terms.append(sql.SQL("{} @> %s::uuid[]").format(sql.Identifier(column)))
                self.values.append([value])
            else:
                terms.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
                self.values.append(value)
        self.filters.append(sql.SQL("(") + sql.SQL(" OR ").join(terms) + sql.SQL(")"))
        return self

    def update(self, payload):
        assert self.name == "notifications" and set(payload) == {"read_at"}
        self.changes = payload
        return self

    def execute(self):
        values = list(self.values)
        if self.changes is None:
            projection = sql.SQL("*") if self.columns == ["*"] else self.projection()
            statement = sql.SQL("SELECT {} FROM public.{}").format(projection, sql.Identifier(self.name))
        else:
            statement = sql.SQL("UPDATE public.{} SET read_at=%s").format(sql.Identifier(self.name))
            values.insert(0, self.changes["read_at"])
        if self.filters:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(self.filters)
        if self.changes is not None:
            statement += sql.SQL(" RETURNING *")
            statement = sql.SQL("WITH changed AS ({}) SELECT to_jsonb(r) FROM changed r").format(statement)
        else:
            if self.orders:
                statement += sql.SQL(" ORDER BY ") + sql.SQL(",").join(self.orders)
            if self.bounds:
                statement += sql.SQL(" LIMIT %s OFFSET %s")
                values.extend(self.bounds)
            statement = sql.SQL("SELECT to_jsonb(r) FROM ({}) r").format(statement)
        return execute(self.database, statement, values)


class WorkflowTransport:
    def __init__(self, database):
        self.database = database

    def table(self, name):
        return WorkflowTable(self.database, name)

    def rpc(self, name, params):
        assert name in {"create_hr_request", "review_hr_request", "active_delegation_principals",
                        "assign_academy_course", "update_academy_progress", "submit_academy_quiz", "advance_learning_tracks"}
        if name == "active_delegation_principals":
            statement = sql.SQL("SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM public.{}(%s) t").format(sql.Identifier(name))
        else:
            # PostgREST decodes JSON amounts as numeric; psycopg otherwise
            # types Python floats as double precision, which changes overload resolution.
            arguments = sql.SQL(",").join(
                sql.SQL("{} => %s::numeric" if key == "p_amount" else "{} => %s").format(sql.Identifier(key))
                for key in params
            )
            statement = sql.SQL("SELECT public.{}({})").format(sql.Identifier(name), arguments)
        values = [Jsonb(value) if isinstance(value, dict) else value for value in params.values()]
        return SimpleNamespace(execute=lambda: execute(self.database, statement, values, rpc=True))


@pytest.fixture
def workflow_client(team_db, monkeypatch):
    # team_db is an independently created UUID database. Clear only its
    # per-scenario fixtures, never the DSN's original empty database.
    with team_db.connect(None) as connection:
        connection.execute("TRUNCATE employee_profiles, courses, auth.users CASCADE")
        for person, role, manager in [
            (DIRECTOR, "director", None), (MANAGER, "manager", None),
            (OTHER_MANAGER, "manager", None), (HR, "hr_admin", None),
            (WORKER, "worker", MANAGER), (OTHER_WORKER, "worker", OTHER_MANAGER),
            (UNMANAGED_WORKER, "worker", None),
        ]:
            connection.execute("INSERT INTO auth.users(id,email) VALUES (%s,%s)", (person, f"{person}@example.test"))
            connection.execute("""INSERT INTO employee_profiles
                (id,auth_user_id,employee_code,full_name,email,company,job_title,department,
                 manager_id,hired_at,vacation_days_remaining,role)
                VALUES (%s,%s,%s,%s,%s,'Test','Test','Test',%s,'2024-01-01',20,%s)""",
                (person, person, person, role, f"{person}@example.test", manager, role))
        quiz = [{"id": "q1", "prompt": "First?", "options": ["A", "B"], "answer_index": 1},
                {"id": "q2", "prompt": "Second?", "options": ["A", "B"], "answer_index": 0}]
        connection.execute("""INSERT INTO courses(id,title,description,duration_minutes,material_markdown,quiz,passing_score)
            VALUES (%s,'Security basics','A short demo course',15,'## Read this material',%s,80)""",
            (COURSE, Jsonb(quiz)))
    with team_db.connect() as connection:
        initial_requests = {owner: create_request(connection, owner, **leave_payload(offset=30, days=3))["id"]
                            for owner in (WORKER, OTHER_WORKER)}
        connection.execute("SELECT assign_academy_course(%s,%s,%s)", (MANAGER, WORKER, COURSE))
        connection.execute("SELECT update_academy_progress(%s,%s,20)", (WORKER, COURSE))
    with team_db.connect(None) as connection:
        # Initial fixtures were created through real commands; later assertions
        # inspect only notifications generated by the action under test.
        # The Telegram delivery queue references notifications. Both are only
        # scenario fixtures inside this disposable UUID database.
        connection.execute("TRUNCATE telegram_outbox, notifications")
    database = SimpleNamespace(connect=team_db.connect, initial_requests=initial_requests)
    transport = WorkflowTransport(database)
    for module in (requests, academy, notifications):
        monkeypatch.setattr(module, "get_supabase_client", lambda: transport)
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
    client, database, current_actor = workflow_client
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [request_id(database)]

    current_actor["value"] = actor(MANAGER, "manager")
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {request_id(database)}

    current_actor["value"] = actor(HR, "hr_admin")
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {request_id(database), request_id(database, OTHER_WORKER)}


def test_worker_cannot_list_another_employee_requests(workflow_client):
    client, database, _ = workflow_client
    response = client.get(f"/api/v1/requests?employee_id={OTHER_WORKER}")
    assert response.status_code == 403


def test_creating_leave_request_sets_pending_and_notifies_manager(workflow_client):
    client, database, _ = workflow_client
    payload = leave_payload()
    response = client.post(
        "/api/v1/requests",
        json=payload,
    )
    assert response.status_code == 201
    created = response.json()
    assert created["employee_id"] == WORKER
    assert created["status"] == "pending"
    assert created["start_date"] == payload["start_date"]
    assert created["end_date"] == payload["end_date"]
    assert created["leave_days"] == 5
    manager_notifications = [item for item in rows(database, "notifications") if item["employee_id"] == MANAGER]
    assert len(manager_notifications) == 1
    assert manager_notifications[0]["notification_type"] == "request_created"
    assert manager_notifications[0]["request_id"] == created["id"]


def test_unassigned_employee_request_notifies_hr(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(UNMANAGED_WORKER, "worker")
    response = client.post("/api/v1/requests", json={"request_type": "advance", "amount": 2500})
    assert response.status_code == 201
    hr_notifications = [item for item in rows(database, "notifications") if item["employee_id"] == HR]
    assert len(hr_notifications) == 1
    assert hr_notifications[0]["notification_type"] == "request_created"
    assert hr_notifications[0]["request_id"] == response.json()["id"]


def test_worker_cannot_review_request(workflow_client):
    client, database, _ = workflow_client
    response = client.patch(request_path(database), json={"status": "approved"})
    assert response.status_code == 403


def test_manager_can_review_direct_report_and_employee_is_notified(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    response = client.patch(
        request_path(database),
        json={"status": "approved", "reviewer_comment": "Approved"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending_hr"
    assert response.json()["manager_reviewed_by"] == MANAGER
    assert response.json()["manager_reviewer_comment"] == "Approved"
    assert next(item for item in rows(database, "employee_profiles") if item["id"] == WORKER)["vacation_days_remaining"] == 20
    employee_notifications = [item for item in rows(database, "notifications") if item["employee_id"] == WORKER]
    assert len(employee_notifications) == 1
    assert employee_notifications[0]["notification_type"] == "request_pending_hr"
    assert employee_notifications[0]["request_id"] == request_id(database)
    hr_notifications = [item for item in rows(database, "notifications") if item["employee_id"] == HR]
    assert len(hr_notifications) == 1
    assert hr_notifications[0]["notification_type"] == "request_pending_hr"
    repeated_review = client.patch(request_path(database), json={"status": "rejected", "reviewer_comment": "Please reschedule"})
    assert repeated_review.status_code == 409


def test_manager_cannot_review_unrelated_employee_and_hr_cannot_bypass_manager(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    denied = client.patch(request_path(database, OTHER_WORKER), json={"status": "rejected", "reviewer_comment": "Please reschedule"})
    assert denied.status_code == 403
    current_actor["value"] = actor(HR, "hr_admin")
    premature = client.patch(request_path(database, OTHER_WORKER), json={"status": "rejected", "reviewer_comment": "Please reschedule"})
    assert premature.status_code == 409


def test_worker_request_goes_to_manager_then_hr_even_if_manager_reports_to_director(workflow_client):
    client, database, current_actor = workflow_client
    with database.connect(None) as connection:
        connection.execute("UPDATE employee_profiles SET manager_id=%s WHERE id=%s", (DIRECTOR, MANAGER))

    current_actor["value"] = actor(MANAGER, "manager")
    manager_decision = client.patch(
        request_path(database),
        json={"status": "approved", "reviewer_comment": "Одобрено руководителем"},
    )
    assert manager_decision.status_code == 200
    assert manager_decision.json()["status"] == "pending_hr"
    assert manager_decision.json()["manager_reviewed_by"] == MANAGER
    assert not any(item["notification_type"] == "request_pending_director" for item in rows(database, "notifications"))

    current_actor["value"] = actor(DIRECTOR, "director")
    director_inbox = client.get("/api/v1/requests")
    assert director_inbox.status_code == 200
    assert request_id(database) not in {item["id"] for item in director_inbox.json()}
    director_cannot_review_worker_request = client.patch(
        request_path(database),
        json={"status": "approved"},
    )
    assert director_cannot_review_worker_request.status_code == 403

    current_actor["value"] = actor(HR, "hr_admin")
    hr_decision = client.patch(
        request_path(database),
        json={"status": "approved", "reviewer_comment": "Финальное решение HR"},
    )
    assert hr_decision.status_code == 200
    assert hr_decision.json()["status"] == "approved"
    assert hr_decision.json()["hr_reviewed_by"] == HR


def test_director_cannot_review_worker_request_or_another_managers_branch(workflow_client):
    client, database, current_actor = workflow_client
    with database.connect(None) as connection:
        connection.execute("UPDATE employee_profiles SET manager_id=%s WHERE id=%s", (DIRECTOR, MANAGER))
    current_actor["value"] = actor(DIRECTOR, "director")
    premature = client.patch(
        request_path(database), json={"status": "approved"}
    )
    unrelated = client.patch(
        request_path(database, OTHER_WORKER), json={"status": "approved"}
    )
    assert premature.status_code == 403
    assert unrelated.status_code == 403


@pytest.mark.parametrize("final_status", ["approved", "rejected"])
def test_hr_makes_final_decision_after_manager_approval(workflow_client, final_status):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    manager_response = client.patch(
        request_path(database),
        json={"status": "approved", "reviewer_comment": "Manager approved"},
    )
    assert manager_response.status_code == 200
    assert manager_response.json()["status"] == "pending_hr"

    current_actor["value"] = actor(HR, "hr_admin")
    hr_response = client.patch(
        request_path(database),
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
    worker_balance = next(item for item in rows(database, "employee_profiles") if item["id"] == WORKER)["vacation_days_remaining"]
    assert worker_balance == (17 if final_status == "approved" else 20)
    employee_notifications = [item for item in rows(database, "notifications") if item["employee_id"] == WORKER]
    assert sorted(item["notification_type"] for item in employee_notifications) == [
        "request_pending_hr",
        "request_status_changed",
    ]


def test_manager_rejection_is_final_without_hr_handoff(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(MANAGER, "manager")
    response = client.patch(
        request_path(database),
        json={"status": "rejected", "reviewer_comment": "Please reschedule"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["manager_reviewed_by"] == MANAGER
    assert response.json()["reviewed_by"] == MANAGER
    assert not any(item["employee_id"] == HR for item in rows(database, "notifications"))


def test_hr_can_review_request_directly_when_employee_has_no_manager(workflow_client):
    client, database, current_actor = workflow_client
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
    with database.connect(None) as connection:
        # Simulate an externally corrected official balance after reservation.
        connection.execute("UPDATE employee_profiles SET vacation_days_remaining=2 WHERE id=%s", (WORKER,))
    current_actor["value"] = actor(MANAGER, "manager")
    manager_decision = client.patch(
        request_path(database), json={"status": "approved"}
    )
    assert manager_decision.status_code == 200

    current_actor["value"] = actor(HR, "hr_admin")
    hr_decision = client.patch(
        request_path(database), json={"status": "approved"}
    )
    assert hr_decision.status_code == 409
    assert "Недостаточно дней отпуска" in hr_decision.json()["detail"]
    assert next(item for item in rows(database, "hr_requests") if item["id"] == request_id(database))["status"] == "pending_hr"
    assert next(item for item in rows(database, "employee_profiles") if item["id"] == WORKER)["vacation_days_remaining"] == 2
    assert not any(item["event_type"] == "approved" for item in rows(database, "request_events"))


def test_manager_leave_request_goes_to_director_then_hr(workflow_client):
    client, database, current_actor = workflow_client
    director_id = DIRECTOR
    with database.connect(None) as connection:
        connection.execute("UPDATE employee_profiles SET manager_id=%s WHERE id=%s", (director_id, MANAGER))

    # The manager submits their own leave request. The direct-manager relation
    # routes it to the director even though the requester also has role=manager.
    current_actor["value"] = actor(MANAGER, "manager")
    submitted = client.post(
        "/api/v1/requests",
        json={**leave_payload(offset=70, days=6), "comment": "Отпуск руководителя"},
    )
    assert submitted.status_code == 201
    request_id = submitted.json()["id"]
    assert submitted.json()["employee_id"] == MANAGER
    assert any(
        item["employee_id"] == director_id
        and item["notification_type"] == "request_created"
        and item["request_id"] == request_id
        for item in rows(database, "notifications")
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
    manager_balance = next(item for item in rows(database, "employee_profiles") if item["id"] == MANAGER)["vacation_days_remaining"]
    assert manager_balance == 14


def test_manager_can_assign_only_direct_reports_and_assignment_notifies_employee(workflow_client):
    client, database, current_actor = workflow_client
    with database.connect(None) as connection:
        connection.execute("DELETE FROM course_assignments WHERE employee_id=%s", (WORKER,))
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
        for item in rows(database, "notifications")
    )
    assert client.post("/api/v1/academy/assignments", json=payload).status_code == 409


def test_hr_can_assign_course_outside_manager_team(workflow_client):
    client, database, current_actor = workflow_client
    current_actor["value"] = actor(HR, "hr_admin")
    response = client.post(
        "/api/v1/academy/assignments",
        json={"employee_id": OTHER_WORKER, "course_id": COURSE},
    )
    assert response.status_code == 201


def test_course_material_is_only_visible_when_assigned_or_hr(workflow_client):
    client, database, current_actor = workflow_client
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

    assert client.patch(f"/api/v1/academy/courses/{COURSE}/progress", json={"progress_percent": 90}).status_code == 200
    completed = client.post(f"/api/v1/academy/courses/{COURSE}/complete", json={"answers": {"q1": 1, "q2": 0}})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    response = client.patch(f"/api/v1/academy/courses/{COURSE}/progress", json={"progress_percent": 50})
    assert response.status_code == 200
    assert response.json() == completed.json()


def test_course_completion_saves_score_and_notifies_manager(workflow_client):
    client, database, _ = workflow_client
    before_material = client.post(f"/api/v1/academy/courses/{COURSE}/complete", json={"answers": {"q1": 1, "q2": 0}})
    assert before_material.status_code == 409
    assert rows(database, "course_attempts") == []
    assert client.patch(f"/api/v1/academy/courses/{COURSE}/progress", json={"progress_percent": 90}).status_code == 200
    failed = client.post(f"/api/v1/academy/courses/{COURSE}/complete", json={"answers": {"q1": 0, "q2": 0}})
    assert failed.status_code == 200
    assert failed.json()["status"] == "in_progress"
    assert failed.json()["score_percent"] == 50
    assert failed.json()["progress_percent"] == 90
    assert not any(item["notification_type"] in {"course_completed", "team_course_completed"} for item in rows(database, "notifications"))
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
        item for item in rows(database, "notifications")
        if item["employee_id"] == MANAGER and item["notification_type"] == "team_course_completed"
    ]
    assert len(manager_notifications) == 1
    employee_notifications = [
        item for item in rows(database, "notifications")
        if item["employee_id"] == WORKER and item["notification_type"] == "course_completed"
    ]
    assert len(employee_notifications) == 1
    assert re.search(r"100(?:\.0+)?%", employee_notifications[0]["body"])

    repeated = client.post(
        f"/api/v1/academy/courses/{COURSE}/complete",
        json={"answers": {"q1": 1, "q2": 0}},
    )
    assert repeated.status_code == 200
    assert repeated.json() == result
    assert len([
        item for item in rows(database, "notifications")
        if item["notification_type"] in {"course_completed", "team_course_completed"}
    ]) == 2
    assert len(rows(database, "course_attempts")) == 2  # Failed and passed; no retry attempt.


@pytest.mark.parametrize("answers", [{"q1": 1}, {"q1": 1, "q2": 0, "q3": 1}, {"q1": 5, "q2": 0}])
def test_course_completion_rejects_incomplete_or_invalid_answers(workflow_client, answers):
    client, database, _ = workflow_client
    assert client.patch(f"/api/v1/academy/courses/{COURSE}/progress", json={"progress_percent": 90}).status_code == 200
    response = client.post(f"/api/v1/academy/courses/{COURSE}/complete", json={"answers": answers})
    assert response.status_code == 422


def test_notifications_are_private_and_only_owner_can_mark_read(workflow_client):
    client, database, _ = workflow_client
    own_id, other_id = str(uuid4()), str(uuid4())
    with database.connect(None) as connection:
        for notification_id, person in ((own_id, WORKER), (other_id, OTHER_WORKER)):
            connection.execute("""INSERT INTO notifications(id,employee_id,notification_type,title,body)
                VALUES (%s,%s,'test_notice','Test notification','Local test only')""", (notification_id, person))
    response = client.get("/api/v1/notifications")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [own_id]

    assert client.post(f"/api/v1/notifications/{other_id}/read").status_code == 404
    response = client.post(f"/api/v1/notifications/{own_id}/read")
    assert response.status_code == 200
    assert response.json()["read_at"]
    assert client.post(f"/api/v1/notifications/{own_id}/read").json()["read_at"] == response.json()["read_at"]
    assert client.get("/api/v1/notifications?unread_only=true").json() == []
    assert next(item for item in rows(database, "notifications") if item["id"] == other_id)["read_at"] is None
