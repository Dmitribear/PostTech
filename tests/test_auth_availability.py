"""Authentication dependency outages must not masquerade as expired tokens."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ConnectError, ReadTimeout
from postgrest.exceptions import APIError
from supabase_auth.errors import (
    AuthApiError,
    AuthInvalidJwtError,
    AuthRetryableError,
    AuthSessionMissingError,
    AuthUnknownError,
)

from app.presentation.http.routes import local_ai as ai
from app.presentation.http import security


SOURCE_ID = "20000000-0000-4000-8000-000000000001"
AUTH_USER_ID = "40000000-0000-4000-8000-000000000001"
PROFILE_ID = "40000000-0000-4000-8000-000000000002"
INTERNAL = "internal-marker-do-not-expose"
PATHS = [
    ("POST", "/api/v1/ai/local/ask"),
    ("GET", f"/api/v1/ai/local/sources/{SOURCE_ID}"),
]


@pytest.fixture
def authenticated_api(monkeypatch):
    auth_response = SimpleNamespace(user=SimpleNamespace(id=AUTH_USER_ID))
    get_user = Mock(return_value=auth_response)
    client = SimpleNamespace(auth=SimpleNamespace(get_user=get_user))
    monkeypatch.setattr(security, "get_supabase_client", lambda: client)
    get_profile = Mock(
        return_value={"id": PROFILE_ID, "role": "worker", "manager_id": None}
    )
    monkeypatch.setattr(security, "get_profile_by_auth_id", get_profile)
    ask = Mock(
        return_value={
            "answer": "Test refusal",
            "sources": [],
            "mode": "refusal",
            "grounded": False,
            "escalation_suggested": True,
        }
    )
    source = Mock(return_value=None)
    monkeypatch.setattr(ai, "answer_question", ask)
    monkeypatch.setattr(ai, "get_source_article", source)
    app = FastAPI()
    app.include_router(ai.router, prefix="/api/v1")
    with TestClient(app) as http:
        yield SimpleNamespace(
            http=http,
            get_user=get_user,
            get_profile=get_profile,
            ask=ask,
            source=source,
            auth_response=auth_response,
        )


def request(api, method, path):
    return api.http.request(
        method,
        path,
        headers={"Authorization": "Bearer unit-test-token"},
        json={"question": "Как оформить отпуск?"},
    )


@pytest.mark.parametrize("method,path", PATHS)
@pytest.mark.parametrize(
    "error",
    [
        AuthApiError(INTERNAL, 401, "bad_jwt"),
        AuthApiError(INTERNAL, 403, "bad_jwt"),
        AuthApiError(INTERNAL, 400, "invalid_jwt"),
        AuthApiError(INTERNAL, 403, "session_not_found"),
        AuthInvalidJwtError(INTERNAL),
        AuthSessionMissingError(),
    ],
)
def test_rejected_credentials_remain_401_and_never_reach_knowledge(
    authenticated_api, method, path, error
):
    api = authenticated_api
    api.get_user.side_effect = error
    response = request(api, method, path)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid or expired access token"}
    api.get_profile.assert_not_called()
    api.ask.assert_not_called()
    api.source.assert_not_called()


@pytest.mark.parametrize("method,path", PATHS)
@pytest.mark.parametrize(
    "error",
    [
        AuthRetryableError(INTERNAL, 503),
        AuthApiError(INTERNAL, 500, "unexpected_failure"),
        AuthApiError(INTERNAL, 429, "over_request_rate_limit"),
        AuthApiError(INTERNAL, 403, "not_admin"),
        AuthUnknownError(INTERNAL, ValueError(INTERNAL)),
        ConnectError(INTERNAL),
        ReadTimeout(INTERNAL),
        RuntimeError(INTERNAL),
        ValueError(INTERNAL),
    ],
)
def test_auth_outages_and_unexpected_failures_are_503_without_refresh_challenge(
    authenticated_api, method, path, error
):
    api = authenticated_api
    api.get_user.side_effect = error
    response = request(api, method, path)
    assert response.status_code == 503
    assert "WWW-Authenticate" not in response.headers
    assert response.json() == {"detail": "Supabase Auth is temporarily unavailable"}
    assert INTERNAL not in response.text
    api.get_profile.assert_not_called()
    api.ask.assert_not_called()
    api.source.assert_not_called()


@pytest.mark.parametrize("method,path", PATHS)
@pytest.mark.parametrize(
    "error",
    [
        ConnectError(INTERNAL),
        ReadTimeout(INTERNAL),
        APIError(
            {"message": INTERNAL, "code": "PGRST000", "details": INTERNAL, "hint": None}
        ),
        RuntimeError(INTERNAL),
        ValueError(INTERNAL),
    ],
)
def test_profile_lookup_failures_are_503_before_any_answer(
    authenticated_api, method, path, error
):
    api = authenticated_api
    api.get_profile.side_effect = error
    response = request(api, method, path)
    assert response.status_code == 503
    assert response.json() == {"detail": "HR database is unavailable; retry later"}
    assert "WWW-Authenticate" not in response.headers
    assert INTERNAL not in response.text
    api.ask.assert_not_called()
    api.source.assert_not_called()


def test_missing_bearer_is_401_without_calling_supabase(authenticated_api):
    api = authenticated_api
    response = api.http.post(
        "/api/v1/ai/local/ask", json={"question": "Как оформить отпуск?"}
    )
    assert response.status_code == 401
    api.get_user.assert_not_called()
    api.get_profile.assert_not_called()
    api.ask.assert_not_called()


def test_user_missing_from_auth_is_401(authenticated_api):
    api = authenticated_api
    api.get_user.return_value = SimpleNamespace(user=None)
    response = request(api, "POST", "/api/v1/ai/local/ask")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    api.get_profile.assert_not_called()


def test_missing_hr_profile_remains_403(authenticated_api):
    api = authenticated_api
    api.get_profile.return_value = None
    response = request(api, "POST", "/api/v1/ai/local/ask")
    assert response.status_code == 403
    assert response.json() == {
        "detail": "User has no HR profile; contact an administrator"
    }
    api.ask.assert_not_called()


@pytest.mark.parametrize("role", ["worker", "manager", "hr_admin"])
def test_successful_auth_preserves_profile_role_and_identifiers(
    authenticated_api, role
):
    api = authenticated_api
    api.get_profile.return_value = {"id": PROFILE_ID, "role": role, "manager_id": None}
    actor = security.get_current_user(SimpleNamespace(credentials="unit-test-token"))
    assert actor.id == PROFILE_ID
    assert actor.auth_user_id == AUTH_USER_ID
    assert actor.role == role
    assert actor.manager_id is None
    api.get_profile.assert_called_once_with(AUTH_USER_ID)


def test_same_valid_token_can_succeed_after_a_temporary_outage(authenticated_api):
    api = authenticated_api
    api.get_user.side_effect = [AuthRetryableError(INTERNAL, 503), api.auth_response]
    assert request(api, "POST", "/api/v1/ai/local/ask").status_code == 503
    assert request(api, "POST", "/api/v1/ai/local/ask").status_code == 200
    assert [call.args for call in api.get_user.call_args_list] == [
        ("unit-test-token",)
    ] * 2
    api.ask.assert_called_once()
