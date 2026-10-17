from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.api.routes import auth
from app.core.config import get_settings
from app.db.supabase import get_supabase_auth_client
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("extra", [
    {"role": "hr_admin"},
    {"user_metadata": {"role": "hr_admin"}},
    {"auth_user_id": "another-account"},
])
def test_public_registration_rejects_role_or_identity_assignment(monkeypatch, extra) -> None:
    def unexpected_auth_call():
        pytest.fail("Role or identity injection must be rejected before account creation")

    monkeypatch.setattr(auth, "get_supabase_auth_client", unexpected_auth_call)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "worker@example.test", "password": "safe-password", **extra},
    )

    assert response.status_code == 422


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        access_token="access-token",
        refresh_token="refresh-token",
        token_type="bearer",
        expires_in=3600,
    )


def test_register_creates_supabase_account_and_returns_session_when_available(
    monkeypatch,
) -> None:
    calls: list[dict] = []
    fake_user = SimpleNamespace(id="user-123", email="worker@example.test")

    def sign_up(credentials: dict) -> SimpleNamespace:
        calls.append(credentials)
        return SimpleNamespace(user=fake_user, session=_session())

    fake_client = SimpleNamespace(auth=SimpleNamespace(sign_up=sign_up))
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: fake_client)

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "worker@example.test", "password": "safe-password"},
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == "user-123"
    assert response.json()["access_token"] == "access-token"
    assert response.json()["email_confirmation_required"] is False
    assert "password" not in response.json()
    assert calls == [{"email": "worker@example.test", "password": "safe-password"}]


def test_register_reports_email_confirmation_when_supabase_returns_no_session(
    monkeypatch,
) -> None:
    fake_user = SimpleNamespace(id="user-123", email="worker@example.test")
    fake_client = SimpleNamespace(
        auth=SimpleNamespace(
            sign_up=lambda _credentials: SimpleNamespace(user=fake_user, session=None)
        )
    )
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: fake_client)

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "worker@example.test", "password": "safe-password"},
    )

    assert response.status_code == 201
    assert response.json()["email_confirmation_required"] is True
    assert "access_token" not in response.json()


def test_register_returns_supabase_error_details(monkeypatch) -> None:
    def fail_signup(_credentials: dict) -> None:
        from supabase_auth.errors import AuthApiError

        raise AuthApiError("User already registered", 400, "user_already_exists")

    fake_client = SimpleNamespace(auth=SimpleNamespace(sign_up=fail_signup))
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: fake_client)

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "worker@example.test", "password": "safe-password"},
    )

    assert response.status_code == 400
    assert "User already registered" in response.json()["detail"]


def test_login_returns_supabase_bearer_and_refresh_tokens(monkeypatch) -> None:
    fake_user = SimpleNamespace(id="user-123", email="worker@example.test")
    calls: list[dict] = []

    def sign_in(credentials: dict) -> SimpleNamespace:
        calls.append(credentials)
        return SimpleNamespace(user=fake_user, session=_session())

    fake_client = SimpleNamespace(auth=SimpleNamespace(sign_in_with_password=sign_in))
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: fake_client)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "worker@example.test", "password": "safe-password"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "access-token"
    assert response.json()["refresh_token"] == "refresh-token"
    assert calls == [{"email": "worker@example.test", "password": "safe-password"}]


def test_login_rejects_invalid_credentials(monkeypatch) -> None:
    def reject_credentials(_credentials: dict) -> None:
        from supabase_auth.errors import AuthApiError

        raise AuthApiError("Invalid login credentials", 400, "invalid_credentials")

    fake_client = SimpleNamespace(
        auth=SimpleNamespace(sign_in_with_password=reject_credentials)
    )
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: fake_client)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "worker@example.test", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_auth_routes_report_missing_supabase_public_key(monkeypatch) -> None:
    def missing_auth_key() -> None:
        raise RuntimeError("missing config")

    monkeypatch.setattr(auth, "get_supabase_auth_client", missing_auth_key)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "worker@example.test", "password": "safe-password"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Supabase Auth is not configured"}


def test_empty_compose_environment_returns_503_instead_of_settings_error(monkeypatch) -> None:
    for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_KEY"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    get_supabase_auth_client.cache_clear()
    monkeypatch.setattr(auth, "get_supabase_auth_client", get_supabase_auth_client)

    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "worker@example.test", "password": "safe-password"},
        )
    finally:
        get_settings.cache_clear()
        get_supabase_auth_client.cache_clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Supabase Auth is not configured"}
