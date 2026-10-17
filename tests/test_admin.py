from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.api.routes import admin
from app.core import security
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext


HR_ID = "10000000-0000-4000-8000-000000000001"
EMPLOYEE_ID = "10000000-0000-4000-8000-000000000002"
AUTH_ID = "20000000-0000-4000-8000-000000000001"
EMPLOYEES_URL = "/api/v1/admin/employees"
ROLE_URL = f"{EMPLOYEES_URL}/{EMPLOYEE_ID}/role"
PRIVATE_DETAIL = "private upstream credential detail"


@pytest.fixture
def admin_client(monkeypatch):
    query = Mock()
    for method in ("select", "order", "range"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    rpc_query = Mock()
    rpc_query.execute.return_value = SimpleNamespace(data=[{
        "employee_id": EMPLOYEE_ID,
        "previous_role": "worker",
        "role": "manager",
    }])
    database = SimpleNamespace(
        table=Mock(return_value=query),
        rpc=Mock(return_value=rpc_query),
    )
    database_provider = Mock(return_value=database)
    monkeypatch.setattr(admin, "get_supabase_client", database_provider)

    # Never let a missing dependency override contact the configured Supabase.
    auth_provider = Mock(side_effect=AssertionError("Unexpected Auth database call"))
    monkeypatch.setattr(security, "get_supabase_client", auth_provider)
    current_actor = {"value": UserContext(
        id=HR_ID, auth_user_id=AUTH_ID, role="hr_admin",
    )}
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: current_actor["value"]
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client,
                actor=current_actor,
                database=database,
                provider=database_provider,
                auth_provider=auth_provider,
                query=query,
                rpc_query=rpc_query,
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def _admin_request(client, operation):
    if operation == "list":
        return client.get(EMPLOYEES_URL)
    return client.patch(ROLE_URL, json={"role": "hr_admin"})


@pytest.mark.parametrize("operation", ["list", "assign"])
def test_admin_endpoints_require_bearer_authentication(admin_client, operation):
    app.dependency_overrides.pop(get_current_user)

    response = _admin_request(admin_client.client, operation)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    admin_client.provider.assert_not_called()
    admin_client.auth_provider.assert_not_called()


@pytest.mark.parametrize("role", ["worker", "manager", "director"])
@pytest.mark.parametrize("operation", ["list", "assign"])
def test_non_admins_cannot_list_employees_or_assign_roles(admin_client, role, operation):
    admin_client.actor["value"] = UserContext(
        id=EMPLOYEE_ID, auth_user_id=AUTH_ID, role=role,
    )

    response = _admin_request(admin_client.client, operation)

    assert response.status_code == 403
    assert response.json() == {"detail": "HR administrator role required"}
    admin_client.provider.assert_not_called()
    admin_client.database.table.assert_not_called()
    admin_client.database.rpc.assert_not_called()


@pytest.mark.parametrize("initial_role,new_role,first_status,next_status", [
    ("hr_admin", "worker", 200, 403),
    ("worker", "hr_admin", 403, 200),
])
def test_role_changes_apply_to_existing_and_refreshed_tokens(
    admin_client, monkeypatch, initial_role, new_role, first_status, next_status
):
    app.dependency_overrides.pop(get_current_user)
    auth_client = SimpleNamespace(auth=SimpleNamespace(get_user=Mock(
        return_value=SimpleNamespace(user=SimpleNamespace(id=AUTH_ID)),
    )))
    admin_client.auth_provider.side_effect = None
    admin_client.auth_provider.return_value = auth_client
    profile = {"id": HR_ID, "auth_user_id": AUTH_ID, "role": initial_role, "manager_id": None}
    profile_lookup = Mock(side_effect=lambda _auth_id: dict(profile))
    monkeypatch.setattr(security, "get_profile_by_auth_id", profile_lookup)

    first = admin_client.client.get(EMPLOYEES_URL, headers={"Authorization": "Bearer existing-token"})
    assert first.status_code == first_status
    profile["role"] = new_role
    for token in ("existing-token", "refreshed-token"):
        admin_client.provider.reset_mock()
        response = admin_client.client.get(EMPLOYEES_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == next_status
        if next_status == 403:
            admin_client.provider.assert_not_called()
        else:
            admin_client.provider.assert_called_once()

    assert [call.args for call in profile_lookup.call_args_list] == [(AUTH_ID,)] * 3
    assert [call.args for call in auth_client.auth.get_user.call_args_list] == [
        ("existing-token",), ("existing-token",), ("refreshed-token",),
    ]


@pytest.mark.parametrize(
    ("params", "expected_range"),
    [({}, (0, 49)), ({"offset": 20, "limit": 10}, (20, 29)), ({"limit": 100}, (0, 99))],
)
def test_hr_employee_list_is_paginated_and_filters_private_fields(
    admin_client, params, expected_range
):
    public_profile = {
        "id": EMPLOYEE_ID,
        "full_name": "Demo Employee",
        "email": "employee@example.test",
        "role": "worker",
        "manager_id": HR_ID,
    }
    admin_client.query.execute.return_value = SimpleNamespace(data=[{
        **public_profile,
        "auth_user_id": AUTH_ID,
        "access_token": PRIVATE_DETAIL,
        "password": PRIVATE_DETAIL,
        "vacation_days_remaining": 20,
        "employee_code": "DEMO-001",
    }])

    response = admin_client.client.get(EMPLOYEES_URL, params=params)

    assert response.status_code == 200
    assert response.json() == [public_profile]
    assert PRIVATE_DETAIL not in response.text
    admin_client.database.table.assert_called_once_with("employee_profiles")
    admin_client.query.select.assert_called_once_with("id,full_name,email,role,manager_id")
    assert [call.args for call in admin_client.query.order.call_args_list] == [("full_name",), ("id",)]
    admin_client.query.range.assert_called_once_with(*expected_range)
    admin_client.database.rpc.assert_not_called()


@pytest.mark.parametrize("rows", [None, []])
def test_hr_employee_list_accepts_empty_pages(admin_client, rows):
    admin_client.query.execute.return_value = SimpleNamespace(data=rows)
    response = admin_client.client.get(EMPLOYEES_URL, params={"offset": 500})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("params", [
    {"offset": -1}, {"limit": 0}, {"limit": 101}, {"offset": "invalid"},
])
def test_invalid_pagination_is_rejected_before_storage(admin_client, params):
    response = admin_client.client.get(EMPLOYEES_URL, params=params)
    assert response.status_code == 422
    admin_client.provider.assert_not_called()


@pytest.mark.parametrize("role", ["worker", "manager", "director", "hr_admin"])
def test_hr_assigns_all_supported_roles_using_authenticated_actor(admin_client, role):
    expected = {"employee_id": EMPLOYEE_ID, "previous_role": "manager", "role": role}
    admin_client.rpc_query.execute.return_value = SimpleNamespace(data=[{
        **expected, "auth_user_id": AUTH_ID, "private_detail": PRIVATE_DETAIL,
    }])

    response = admin_client.client.patch(ROLE_URL, json={"role": role})

    assert response.status_code == 200
    assert response.json() == expected
    assert PRIVATE_DETAIL not in response.text
    admin_client.database.rpc.assert_called_once_with("assign_employee_role", {
        "p_actor_id": HR_ID,
        "p_employee_id": EMPLOYEE_ID,
        "p_role": role,
    })
    admin_client.database.table.assert_not_called()


@pytest.mark.parametrize("extra", [
    {"p_actor_id": EMPLOYEE_ID},
    {"employee_id": HR_ID},
    {"auth_user_id": AUTH_ID},
    {"manager_id": HR_ID},
    {"full_name": "Changed official name"},
])
def test_role_assignment_rejects_forged_identity_and_official_profile_fields(admin_client, extra):
    response = admin_client.client.patch(ROLE_URL, json={"role": "manager", **extra})
    assert response.status_code == 422
    admin_client.provider.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"role": "admin"}, {"role": None}, {"role": 1}])
def test_role_assignment_requires_a_supported_role(admin_client, payload):
    response = admin_client.client.patch(ROLE_URL, json=payload)
    assert response.status_code == 422
    admin_client.provider.assert_not_called()


def test_role_assignment_requires_uuid_employee_id(admin_client):
    response = admin_client.client.patch(f"{EMPLOYEES_URL}/not-a-uuid/role", json={"role": "manager"})
    assert response.status_code == 422
    admin_client.provider.assert_not_called()


@pytest.mark.parametrize("role", ["worker", "manager", "director"])
def test_hr_cannot_remove_own_administrator_role(admin_client, role):
    response = admin_client.client.patch(f"{EMPLOYEES_URL}/{HR_ID}/role", json={"role": role})
    assert response.status_code == 409
    assert response.json() == {"detail": "You cannot remove your own HR administrator role"}
    admin_client.provider.assert_not_called()


@pytest.mark.parametrize("employee_id,role", [(HR_ID, "hr_admin"), (EMPLOYEE_ID, "worker")])
def test_unchanged_role_is_a_successful_noop(admin_client, employee_id, role):
    expected = {"employee_id": employee_id, "previous_role": role, "role": role}
    admin_client.rpc_query.execute.return_value = SimpleNamespace(data=[expected])

    response = admin_client.client.patch(f"{EMPLOYEES_URL}/{employee_id}/role", json={"role": role})

    assert response.status_code == 200
    assert response.json() == expected
    admin_client.database.rpc.assert_called_once_with("assign_employee_role", {
        "p_actor_id": HR_ID, "p_employee_id": employee_id, "p_role": role,
    })


@pytest.mark.parametrize("code,expected_status,expected_detail", [
    ("42501", 403, "HR administrator role required"),
    ("P0002", 404, "Employee not found"),
    ("PT409", 409, "You cannot remove your own HR administrator role"),
    ("PT412", 409, "Reassign this employee's direct reports before removing their supervisor role"),
    ("PGRST202", 503, "Role administration is unavailable; check database migration 0004"),
    ("42883", 503, "Role administration is unavailable; check database migration 0004"),
])
def test_role_rpc_failures_are_enforced_and_upstream_details_are_hidden(
    admin_client, code, expected_status, expected_detail
):
    # The dependency still says HR, but RPC may observe a concurrently revoked role.
    admin_client.rpc_query.execute.side_effect = APIError({
        "code": code, "message": PRIVATE_DETAIL, "details": PRIVATE_DETAIL, "hint": PRIVATE_DETAIL,
    })

    response = admin_client.client.patch(ROLE_URL, json={"role": "worker"})

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert PRIVATE_DETAIL not in response.text
    admin_client.database.rpc.assert_called_once()
    admin_client.database.table.assert_not_called()


@pytest.mark.parametrize("operation", ["list", "assign"])
@pytest.mark.parametrize("error_type", [RuntimeError, HTTPError])
def test_storage_failures_return_503_without_upstream_details(admin_client, operation, error_type):
    query = admin_client.query if operation == "list" else admin_client.rpc_query
    query.execute.side_effect = error_type(PRIVATE_DETAIL)

    response = _admin_request(admin_client.client, operation)

    assert response.status_code == 503
    assert PRIVATE_DETAIL not in response.text
    assert response.json()["detail"] == (
        "Employee storage is temporarily unavailable" if operation == "list"
        else "Role administration is temporarily unavailable"
    )


def test_employee_list_database_error_does_not_expose_upstream_details(admin_client):
    admin_client.query.execute.side_effect = APIError({
        "code": "42501", "message": PRIVATE_DETAIL, "details": PRIVATE_DETAIL, "hint": PRIVATE_DETAIL,
    })
    response = admin_client.client.get(EMPLOYEES_URL)
    assert response.status_code == 503
    assert response.json() == {"detail": "Employee storage is temporarily unavailable"}
    assert PRIVATE_DETAIL not in response.text


@pytest.mark.parametrize("rows", [None, []])
def test_empty_role_rpc_response_is_not_reported_as_success(admin_client, rows):
    admin_client.rpc_query.execute.return_value = SimpleNamespace(data=rows)
    response = admin_client.client.patch(ROLE_URL, json={"role": "worker"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Role administration did not return a result"}
