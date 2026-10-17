"""HTTP contracts and read permissions; SQL transactions are tested separately."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.domain.errors import StorageUnavailable
import pytest
from fastapi.testclient import TestClient
from app.domain.errors import StorageError as APIError

from app.application.use_cases import notifications
from app.presentation.http.security import get_current_user
from app.main import app
from app.domain.models import UserContext
from app.application.use_cases import requests as workflow

WORKER, OTHER, MANAGER, HR = [str(UUID(int=i)) for i in range(1, 5)]
REQUEST = str(UUID(int=10))
NOW = "2026-10-16T12:00:00+00:00"
LEAVE = {
    "request_type": "leave",
    "start_date": "2026-11-01",
    "end_date": "2026-11-05",
    "comment": "Leave",
}


def request_row(employee_id=WORKER, request_id=REQUEST, **overrides):
    return {
        "id": request_id,
        "employee_id": employee_id,
        **LEAVE,
        "status": "pending",
        "amount": None,
        "reviewer_comment": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
        "approval_route": "manager",
        "approver_ids": [MANAGER],
        "approvers": [{"id": MANAGER, "full_name": "Manager", "role": "manager"}],
        "cancelled_at": None,
    }


class Query:
    """Small table transport fake; it does not simulate the workflow RPCs."""

    def __init__(self, database, table):
        self.database, self.table = database, table
        self.filters, self.orders = [], []
        self.columns, self.bounds, self.values = "*", None, None

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, name, value):
        self.filters.append(lambda row: row.get(name) == value)
        return self

    def in_(self, name, values):
        self.filters.append(lambda row: row.get(name) in values)
        return self

    def neq(self, name, value):
        self.filters.append(lambda row: row.get(name) != value)
        return self

    def contains(self, name, values):
        self.filters.append(
            lambda row: all(value in row.get(name, []) for value in values)
        )
        return self

    def or_(self, expression):
        def matches(row, expression):
            import re

            parts = re.split(r",(?![^()]*\))(?![^{}]*\})", expression)
            for part in parts:
                if part.startswith("and("):
                    inner = part[4:-1]
                    checks = re.split(r",(?![^{}]*\})", inner)
                    if all(single(row, x) for x in checks):
                        return True
                elif single(row, part):
                    return True
            return False

        def single(row, part):
            field, op, value = part.split(".", 2)
            if op == "eq":
                return row.get(field) == value
            if op == "neq":
                return row.get(field) != value
            if op == "cs":
                return set(value.strip("{}").split(",")) <= set(row.get(field, []))
            if op == "ov":
                return bool(set(value.strip("{}").split(",")) & set(row.get(field, [])))
            raise AssertionError(part)

        self.filters.append(lambda row: matches(row, expression))
        return self

    def is_(self, name, value):
        assert value == "null"
        self.filters.append(lambda row: row.get(name) is None)
        return self

    def order(self, name, desc=False):
        self.orders.append((name, desc))
        return self

    def limit(self, count):
        return self.range(0, count - 1)

    def range(self, start, end):
        self.bounds = (start, end + 1)
        return self

    def update(self, values):
        self.values = values
        return self

    def execute(self):
        rows = [
            row
            for row in self.database.tables[self.table]
            if all(f(row) for f in self.filters)
        ]
        for name, desc in reversed(self.orders):
            rows.sort(key=lambda row: row[name], reverse=desc)
        if self.bounds:
            rows = rows[self.bounds[0] : self.bounds[1]]
        if self.values is not None:
            for row in rows:
                row.update(self.values)
        if self.columns != "*":
            rows = [
                {key: row.get(key) for key in self.columns.split(",")} for row in rows
            ]
        return SimpleNamespace(data=deepcopy(rows))


class Database:
    def __init__(self):
        self.tables = {
            "employee_profiles": [
                {"id": WORKER, "manager_id": MANAGER},
                {"id": OTHER, "manager_id": None},
                {"id": MANAGER, "manager_id": None},
                {"id": HR, "manager_id": None},
            ],
            "hr_requests": [request_row()],
            "request_events": [],
            "notifications": [],
        }
        self.rpc_calls = []
        self.rpc_result = request_row()
        self.error = None

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        if name == "active_delegation_principals":
            return SimpleNamespace(
                execute=lambda: SimpleNamespace(data=getattr(self, "principals", []))
            )
        self.rpc_calls.append((name, params))

        def execute():
            if self.error:
                raise self.error
            return SimpleNamespace(data=deepcopy(self.rpc_result))

        return SimpleNamespace(execute=execute)


@pytest.fixture
def api(monkeypatch):
    database = Database()
    actor = {"user": UserContext(id=WORKER, auth_user_id=str(uuid4()), role="worker")}
    app.dependency_overrides[get_current_user] = lambda: actor["user"]
    monkeypatch.setattr(workflow, "get_data_gateway", lambda: database)
    monkeypatch.setattr(notifications, "get_data_gateway", lambda: database)
    try:
        with TestClient(app) as client:
            yield client, database, actor
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def as_user(actor, employee_id, role):
    actor["user"] = UserContext(id=employee_id, auth_user_id=str(uuid4()), role=role)


def test_deputy_reads_only_pending_assigned_requests_and_own_decisions(api):
    client, database, actor = api
    database.principals = [MANAGER]
    as_user(actor, OTHER, "manager")
    response = client.get("/api/v1/requests?scope=review")
    assert [r["id"] for r in response.json()] == [REQUEST]
    assert response.json()[0]["can_review"] is True
    assert client.get(f"/api/v1/requests/{REQUEST}").status_code == 200
    database.principals = []
    assert client.get(f"/api/v1/requests/{REQUEST}").status_code == 403
    assert client.get("/api/v1/requests?scope=review").json() == []
    database.tables["hr_requests"][0].update(status="approved", reviewed_by=OTHER)
    assert client.get(f"/api/v1/requests/{REQUEST}").json()["can_review"] is False
    assert len(client.get("/api/v1/requests?scope=review").json()) == 1


def test_create_uses_authenticated_employee_and_idempotency_header(api):
    client, database, _ = api
    key = str(uuid4())
    database.rpc_result["idempotency_key"] = key
    response = client.post(
        "/api/v1/requests", json=LEAVE, headers={"Idempotency-Key": key}
    )
    assert response.status_code == 201
    assert response.json()["id"] == REQUEST
    assert "idempotency_key" not in response.json()
    assert database.rpc_calls == [
        (
            "create_hr_request",
            {
                "p_actor_id": WORKER,
                "p_idempotency_key": key,
                "p_amount": None,
                **{f"p_{name}": value for name, value in LEAVE.items()},
            },
        )
    ]


def test_legacy_create_without_header_gets_fresh_command_ids(api):
    client, database, _ = api
    for _ in range(2):
        assert client.post("/api/v1/requests", json=LEAVE).status_code == 201
    keys = [UUID(params["p_idempotency_key"]) for _, params in database.rpc_calls]
    assert keys[0] != keys[1]


@pytest.mark.parametrize(
    "change",
    [
        {"employee_id": OTHER},
        {"role": "hr_admin"},
        {"status": "approved"},
        {"end_date": "2026-10-01"},
        {"start_date": None},
        {"amount": 100},
        {"comment": "x" * 2001},
    ],
)
def test_invalid_or_spoofed_create_is_rejected_before_database(api, change):
    client, database, _ = api
    assert client.post("/api/v1/requests", json={**LEAVE, **change}).status_code == 422
    assert not database.rpc_calls


@pytest.mark.parametrize(
    "path",
    [
        "/requests/not-a-uuid",
        "/requests/not-a-uuid/history",
        "/requests?employee_id=invalid",
        "/requests?status=unknown",
        "/requests?request_type=unknown",
        "/requests?limit=101",
        "/requests?offset=-1",
    ],
)
def test_invalid_paths_and_filters_return_422(api, path):
    client, _, _ = api
    assert client.get("/api/v1" + path).status_code == 422


def test_invalid_idempotency_key_does_not_submit(api):
    client, database, _ = api
    assert (
        client.post(
            "/api/v1/requests", json=LEAVE, headers={"Idempotency-Key": "bad"}
        ).status_code
        == 422
    )
    assert not database.rpc_calls


@pytest.mark.parametrize(
    ("user", "role", "visible"),
    [
        (WORKER, "worker", {WORKER}),
        (OTHER, "worker", {OTHER}),
        (MANAGER, "manager", {MANAGER, WORKER}),
        (HR, "hr_admin", {WORKER, OTHER, MANAGER}),
    ],
)
def test_list_enforces_role_scope(api, user, role, visible):
    client, database, actor = api
    foreign = request_row(OTHER, str(uuid4()))
    foreign["approver_ids"] = []
    database.tables["hr_requests"] += [foreign, request_row(MANAGER, str(uuid4()))]
    as_user(actor, user, role)
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert {row["employee_id"] for row in response.json()} == visible


def test_list_filters_and_pagination_stay_within_ownership(api):
    client, database, _ = api
    database.tables["hr_requests"] += [
        request_row(WORKER, str(UUID(int=11)), status="approved"),
        request_row(WORKER, str(UUID(int=12))),
        request_row(OTHER, str(UUID(int=13))),
        request_row(
            WORKER,
            str(UUID(int=14)),
            request_type="advance",
            start_date=None,
            end_date=None,
            amount=100,
        ),
    ]
    response = client.get(
        "/api/v1/requests?status=pending&request_type=leave&limit=1&offset=1"
    )
    assert [row["id"] for row in response.json()] == [REQUEST]
    assert client.get(f"/api/v1/requests?employee_id={OTHER}").status_code == 403


@pytest.mark.parametrize("suffix", ["", "/history"])
@pytest.mark.parametrize(
    ("user", "role", "expected"),
    [
        (WORKER, "worker", 200),
        (MANAGER, "manager", 200),
        (HR, "hr_admin", 200),
        (OTHER, "worker", 403),
        (OTHER, "manager", 403),
    ],
)
def test_card_and_history_share_access_rules(api, suffix, user, role, expected):
    client, _, actor = api
    as_user(actor, user, role)
    assert client.get(f"/api/v1/requests/{REQUEST}{suffix}").status_code == expected


def test_history_places_creation_first_when_imported_timestamps_match(api):
    client, database, _ = api
    base = {"request_id": REQUEST, "comment": "", "created_at": NOW}
    database.tables["request_events"] = [
        {
            **base,
            "id": str(UUID(int=20)),
            "actor_id": MANAGER,
            "event_type": "approved",
            "from_status": "pending",
            "to_status": "approved",
        },
        {
            **base,
            "id": str(UUID(int=21)),
            "actor_id": WORKER,
            "event_type": "created",
            "from_status": None,
            "to_status": "pending",
        },
    ]
    response = client.get(f"/api/v1/requests/{REQUEST}/history")
    assert [event["event_type"] for event in response.json()] == ["created", "approved"]


def test_unknown_request_returns_404(api):
    client, _, _ = api
    assert client.get(f"/api/v1/requests/{uuid4()}/history").status_code == 404


def test_worker_cannot_review(api):
    client, database, _ = api
    assert (
        client.patch(
            f"/api/v1/requests/{REQUEST}/review", json={"status": "approved"}
        ).status_code
        == 403
    )
    assert not database.rpc_calls


def test_review_forwards_trusted_reviewer_and_payload(api):
    client, database, actor = api
    as_user(actor, MANAGER, "manager")
    database.rpc_result.update(status="approved", reviewed_by=MANAGER, reviewed_at=NOW)
    response = client.patch(
        f"/api/v1/requests/{REQUEST}/review",
        json={"status": "approved", "reviewer_comment": "OK"},
    )
    assert response.status_code == 200
    assert database.rpc_calls == [
        (
            "review_hr_request",
            {
                "p_actor_id": MANAGER,
                "p_request_id": REQUEST,
                "p_status": "approved",
                "p_reviewer_comment": "OK",
            },
        )
    ]


@pytest.mark.parametrize("code", [403, 404, 409, 422])
def test_database_workflow_errors_are_http_errors(api, code):
    client, database, actor = api
    as_user(actor, MANAGER, "manager")
    database.error = APIError(
        {
            "code": f"PT{code}",
            "message": "Workflow rejected",
            "details": None,
            "hint": None,
        }
    )
    response = client.patch(
        f"/api/v1/requests/{REQUEST}/review", json={"status": "approved"}
    )
    assert response.status_code == code
    assert response.json()["detail"] == "Workflow rejected"


@pytest.mark.parametrize(
    "error",
    [
        APIError(
            {
                "code": "PGRST202",
                "message": "missing rpc",
                "details": None,
                "hint": None,
            }
        ),
        APIError(
            {
                "code": "23514",
                "message": "sensitive DB detail",
                "details": None,
                "hint": None,
            }
        ),
        StorageUnavailable("sensitive connection detail"),
    ],
)
def test_database_failures_are_safe_503(api, error):
    client, database, _ = api
    database.error = error
    response = client.post("/api/v1/requests", json=LEAVE)
    assert response.status_code == 503
    assert "sensitive" not in response.text


def test_notifications_filter_ownership_and_idempotent_read(api):
    client, database, _ = api
    own, foreign = str(uuid4()), str(uuid4())
    base = {
        "request_id": REQUEST,
        "notification_type": "request_status_changed",
        "title": "Status",
        "body": "Approved",
        "read_at": None,
        "created_at": NOW,
    }
    database.tables["notifications"] = [
        {**base, "id": own, "employee_id": WORKER},
        {**base, "id": foreign, "employee_id": OTHER},
    ]
    assert [
        row["id"]
        for row in client.get(
            f"/api/v1/notifications?request_id={REQUEST}&unread_only=true"
        ).json()
    ] == [own]
    first = client.post(f"/api/v1/notifications/{own}/read")
    assert first.status_code == 200
    assert first.json()["read_at"] is not None
    assert client.post(f"/api/v1/notifications/{own}/read").json() == first.json()
    assert client.get("/api/v1/notifications?unread_only=true").json() == []
    assert client.post(f"/api/v1/notifications/{foreign}/read").status_code == 404
    assert database.tables["notifications"][1]["read_at"] is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/requests", LEAVE),
        ("GET", f"/requests/{REQUEST}/history", None),
        ("PATCH", f"/requests/{REQUEST}/review", {"status": "approved"}),
        ("POST", f"/notifications/{UUID(int=20)}/read", None),
    ],
)
def test_new_workflow_endpoints_require_authentication(method, path, body):
    with TestClient(app) as client:
        assert client.request(method, "/api/v1" + path, json=body).status_code == 401


def test_routing_endpoint_precedes_uuid_route_and_uses_session_identity(api):
    client, database, _ = api
    database.rpc_result = {
        "can_submit": True,
        "route": "manager",
        "approvers": [{"id": MANAGER, "full_name": "Manager", "role": "manager"}],
        "message": None,
        "today": "2026-10-16",
        "policy": "Calendar days",
    }
    response = client.get("/api/v1/requests/routing")
    assert response.status_code == 200
    assert response.json()["approvers"][0]["id"] == MANAGER
    assert database.rpc_calls == [("get_hr_request_routing", {"p_actor_id": WORKER})]


def test_routing_reports_missing_approver_without_creating_request(api):
    client, database, _ = api
    database.rpc_result = {
        "can_submit": False,
        "route": "unassigned",
        "approvers": [],
        "message": "No eligible approver is configured; contact HR",
        "today": "2026-10-16",
        "policy": "Calendar days",
    }
    response = client.get("/api/v1/requests/routing")
    assert response.status_code == 200
    assert response.json()["can_submit"] is False
    assert len(database.tables["hr_requests"]) == 1


@pytest.mark.parametrize("reason", [None, "", " \n\t ", "\u00a0"])
def test_rejected_without_visible_reason_never_reaches_database(api, reason):
    client, database, actor = api
    as_user(actor, MANAGER, "manager")
    response = client.patch(
        f"/api/v1/requests/{REQUEST}/review",
        json={"status": "rejected", "reviewer_comment": reason},
    )
    assert response.status_code == 422
    assert not database.rpc_calls


def test_cancel_uses_authenticated_owner_and_hides_internal_snapshot_ids(api):
    client, database, _ = api
    database.rpc_result.update(status="cancelled", cancelled_at=NOW)
    response = client.post(f"/api/v1/requests/{REQUEST}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancelled_at"]
    assert "approver_ids" not in response.json()
    assert database.rpc_calls == [
        ("cancel_hr_request", {"p_actor_id": WORKER, "p_request_id": REQUEST})
    ]


def test_review_inbox_excludes_own_requests_for_all_reviewer_roles(api):
    client, database, actor = api
    database.tables["hr_requests"] += [
        request_row(MANAGER, str(UUID(int=30))),
        request_row(HR, str(UUID(int=31))),
    ]
    for person, role in [(MANAGER, "manager"), (HR, "hr_admin")]:
        as_user(actor, person, role)
        response = client.get("/api/v1/requests?scope=review")
        assert response.status_code == 200
        assert all(row["employee_id"] != person for row in response.json())
        own = client.get("/api/v1/requests?scope=mine").json()
        assert {row["employee_id"] for row in own} == {person}


def test_worker_cannot_access_review_inbox(api):
    client, _, _ = api
    assert client.get("/api/v1/requests?scope=review").status_code == 403


def test_snapshot_access_survives_manager_reassignment(api):
    client, database, actor = api
    database.tables["employee_profiles"][0]["manager_id"] = OTHER
    as_user(actor, MANAGER, "manager")
    assert client.get(f"/api/v1/requests/{REQUEST}").status_code == 200
    assert client.get("/api/v1/requests?scope=review").json()[0]["id"] == REQUEST
    as_user(actor, OTHER, "manager")
    assert client.get(f"/api/v1/requests/{REQUEST}").status_code == 403
    assert client.get("/api/v1/requests?scope=review").json() == []


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/requests/routing"), ("POST", f"/requests/{REQUEST}/cancel")],
)
def test_lifecycle_endpoints_require_authentication(method, path):
    with TestClient(app) as client:
        assert client.request(method, "/api/v1" + path).status_code == 401
