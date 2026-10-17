from uuid import uuid4
import pytest
from app.domain.models import UserContext
from test_academy import api, WORKER, OTHER, MANAGER, HR, COURSE


@pytest.mark.parametrize(
    "path",
    [
        "knowledge",
        "integrations",
        f"knowledge/{COURSE}/history",
        f"integrations/{COURSE}/attempts",
    ],
)
def test_hr_operations_deny_worker_and_manager(api, path):
    client, _, actor = api
    assert client.get("/api/v1/workspace/" + path).status_code == 403
    actor["user"] = UserContext(id=MANAGER, auth_user_id=str(uuid4()), role="manager")
    assert client.get("/api/v1/workspace/" + path).status_code == 403


def test_leave_balance_only_owner_manager_and_hr(api):
    client, db, actor = api
    db.rpc_result = {
        "employee_id": WORKER,
        "official_days": 24,
        "pending_days": 4,
        "approved_unreconciled_days": 5,
        "available_days": 15,
        "holds": [],
    }
    assert client.get("/api/v1/workspace/leave-balance").json()["available_days"] == 15
    assert (
        client.get(f"/api/v1/workspace/leave-balance?employee_id={OTHER}").status_code
        == 404
    )
    actor["user"] = UserContext(id=MANAGER, auth_user_id=str(uuid4()), role="manager")
    assert (
        client.get(f"/api/v1/workspace/leave-balance?employee_id={WORKER}").status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/workspace/leave-balance?employee_id={OTHER}").status_code
        == 404
    )


def test_lesson_actor_comes_from_session_and_knowledge_url_is_safe(api):
    client, db, actor = api
    assert (
        client.post(
            f"/api/v1/workspace/courses/{COURSE}/lessons/first/complete"
        ).status_code
        == 200
    )
    assert db.rpc_calls[-1][1]["p_actor_id"] == WORKER
    actor["user"] = UserContext(id=HR, auth_user_id=str(uuid4()), role="hr_admin")
    body = {
        "id": COURSE,
        "action": "create",
        "data": {
            "title": "Test source",
            "content": "Test material",
            "source_title": "Policy",
            "source_url": "javascript:alert(1)",
        },
    }
    assert client.post("/api/v1/workspace/knowledge", json=body).status_code == 422


def test_past_reviewer_does_not_gain_current_balance_access(api, monkeypatch):
    client, _, actor = api
    actor["user"] = UserContext(id=MANAGER, auth_user_id=str(uuid4()), role="manager")
    monkeypatch.setattr(
        "app.application.use_cases.extensions.get_request",
        lambda *args: {"id": COURSE, "employee_id": OTHER, "can_review": False},
    )
    assert (
        client.get(f"/api/v1/workspace/leave-balance?request_id={COURSE}").status_code
        == 404
    )
    monkeypatch.setattr(
        "app.application.use_cases.extensions.get_request",
        lambda *args: {"id": COURSE, "employee_id": OTHER, "can_review": True},
    )
    # A current snapshot/delegated reviewer can inspect impact even without direct-report access.
    _, db, _ = api
    db.rpc_result = {"holds": [], "available_days": 24}
    assert (
        client.get(f"/api/v1/workspace/leave-balance?request_id={COURSE}").status_code
        == 200
    )


def test_reconciliation_rejects_untrusted_actor_and_half_day_precision(api):
    client, db, actor = api
    body = {
        "id": str(uuid4()),
        "employee_id": WORKER,
        "days": 20,
        "requests": [],
        "note": "Payroll snapshot",
    }
    assert (
        client.post("/api/v1/workspace/leave-balance/reconcile", json=body).status_code
        == 403
    )
    actor["user"] = UserContext(id=HR, auth_user_id=str(uuid4()), role="hr_admin")
    assert (
        client.post(
            "/api/v1/workspace/leave-balance/reconcile", json={**body, "days": 20.2}
        ).status_code
        == 422
    )
