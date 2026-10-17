from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.application.use_cases import profile
from app.presentation.http import security
from app.main import app


PROFILES = {
    "worker": {
        "id": "worker",
        "auth_user_id": "auth-worker",
        "role": "worker",
        "manager_id": "manager",
        "full_name": "Test worker",
    },
    "manager": {
        "id": "manager",
        "auth_user_id": "auth-manager",
        "role": "manager",
        "manager_id": None,
        "full_name": "Test manager",
    },
    "outsider": {
        "id": "outsider",
        "auth_user_id": "auth-outsider",
        "role": "worker",
        "manager_id": "other-manager",
        "full_name": "Test outsider",
    },
    "hr": {
        "id": "hr",
        "auth_user_id": "auth-hr",
        "role": "hr_admin",
        "manager_id": None,
        "full_name": "Test HR",
    },
}


class ProfilesQuery:
    def __init__(self):
        self.filters = []
        self.columns = "*"
        self.count = 100

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, name, value):
        self.filters.append((name, value))
        return self

    def order(self, _):
        return self

    def limit(self, count):
        self.count = count
        return self

    def execute(self):
        rows = [
            deepcopy(row)
            for row in PROFILES.values()
            if all(row.get(k) == v for k, v in self.filters)
        ][: self.count]
        if self.columns != "*":
            rows = [{key: row[key] for key in self.columns.split(",")} for row in rows]
        return SimpleNamespace(data=rows)


@pytest.fixture
def secured_api(monkeypatch):
    def get_user(token):
        if token == "unlinked":
            return SimpleNamespace(user=SimpleNamespace(id="auth-unlinked"))
        if token not in PROFILES:
            from supabase_auth.errors import AuthApiError

            raise AuthApiError("invalid token", 401, "bad_jwt")
        return SimpleNamespace(
            user=SimpleNamespace(
                id=PROFILES[token]["auth_user_id"],
                user_metadata={"role": "hr_admin"},
                role="hr_admin",
            )
        )

    def get_profile(employee_id):
        if employee_id not in PROFILES:
            raise HTTPException(status_code=404, detail="Employee not found")
        return deepcopy(PROFILES[employee_id])

    def table(name):
        assert name == "employee_profiles"
        return ProfilesQuery()

    monkeypatch.setattr(
        security,
        "get_supabase_client",
        lambda: SimpleNamespace(auth=SimpleNamespace(get_user=get_user)),
    )
    monkeypatch.setattr(
        security,
        "get_profile_by_auth_id",
        lambda auth_id: next(
            (
                deepcopy(row)
                for row in PROFILES.values()
                if row["auth_user_id"] == auth_id
            ),
            None,
        ),
    )
    monkeypatch.setattr(profile, "get_profile", get_profile)
    monkeypatch.setattr(
        profile, "get_data_gateway", lambda: SimpleNamespace(table=table)
    )
    monkeypatch.setattr(profile, "get_assigned_courses", lambda client, actor: [])
    monkeypatch.setattr(
        profile, "list_employee_notifications", lambda client, actor: []
    )
    for item in PROFILES.values():
        item.update(
            employee_code=item["id"],
            email=item["id"] + "@example.test",
            company="Test",
            job_title="Test",
            department="Test",
            hired_at="2026-01-01",
            vacation_days_remaining=24,
        )
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("actor", "employee", "expected"),
    [
        ("worker", "worker", 200),
        ("worker", "outsider", 403),
        ("worker", "manager", 403),
        ("manager", "manager", 200),
        ("manager", "worker", 200),
        ("manager", "outsider", 403),
        ("manager", "hr", 403),
        ("hr", "worker", 200),
        ("hr", "outsider", 200),
    ],
)
def test_profile_access_uses_database_role_and_direct_manager_link(
    secured_api, actor, employee, expected
):
    response = secured_api.get(
        f"/api/v1/employees/{employee}",
        headers={
            "Authorization": f"Bearer {actor}",
            "X-Role": "hr_admin",
        },
    )
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["id"] == employee
        assert "auth_user_id" not in response.json()
    else:
        assert PROFILES[employee]["full_name"] not in response.text


@pytest.mark.parametrize(
    ("actor", "expected", "members"),
    [
        ("worker", 403, set()),
        ("manager", 200, {"worker"}),
        ("hr", 200, set(PROFILES)),
    ],
)
def test_team_endpoint_enforces_roles_in_server_queries(
    secured_api, actor, expected, members
):
    response = secured_api.get(
        "/api/v1/team", headers={"Authorization": f"Bearer {actor}"}
    )
    assert response.status_code == expected
    if expected == 200:
        assert {row["id"] for row in response.json()} == members
        assert all("auth_user_id" not in row for row in response.json())


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/profile",
        "/api/v1/team",
        "/api/v1/requests",
        "/api/v1/academy/courses",
        "/api/v1/ai/sources/00000000-0000-0000-0000-000000000101",
    ],
)
def test_unlinked_account_cannot_access_any_hr_area(secured_api, path):
    response = secured_api.get(path, headers={"Authorization": "Bearer unlinked"})
    assert response.status_code == 403
    assert "no HR profile" in response.json()["detail"]


def test_invalid_tokens_cannot_establish_an_hr_role(secured_api):
    response = secured_api.get(
        "/api/v1/profile", headers={"Authorization": "Bearer forged"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_official_profile_has_no_employee_update_endpoint(secured_api):
    response = secured_api.patch(
        "/api/v1/profile",
        headers={"Authorization": "Bearer worker"},
        json={"role": "hr_admin", "vacation_days_remaining": 90},
    )
    assert response.status_code == 405


def test_own_profile_reveals_manager_name_without_managers_hr_record(secured_api):
    response = secured_api.get(
        "/api/v1/profile", headers={"Authorization": "Bearer worker"}
    )
    assert response.status_code == 200
    assert response.json()["manager_name"] == PROFILES["manager"]["full_name"]
    assert response.json()["role"] == "worker"
    assert "auth_user_id" not in response.json()
    assert (
        secured_api.get(
            "/api/v1/employees/manager", headers={"Authorization": "Bearer worker"}
        ).status_code
        == 403
    )
