from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.core.config import get_settings
from app.db.supabase import get_supabase_auth_client
from app.main import app

client = TestClient(app)

REGISTRATION = {"invitation_code": "JP-test-invitation-code", "first_name": "Алексей", "last_name": "Ким", "password": "Safe-password9"}
INVITATION = {"email": "worker@example.test", "role": "worker", "department": "Test", "expires_at": "2026-12-01T00:00:00Z"}


@pytest.fixture(autouse=True)
def fake_invitation_database(monkeypatch):
    monkeypatch.setattr(auth.invitations, "check", lambda *args, **kwargs: INVITATION)
    monkeypatch.setattr(auth.invitations, "prepare", lambda *args, **kwargs: INVITATION)
    monkeypatch.setattr(auth.invitations, "complete", lambda *args, **kwargs: {"profile_id": "profile-1", "role": "worker"})


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
    fake_user = SimpleNamespace(id="user-123", email="worker@example.test", email_confirmed_at="2026-10-16T12:00:00Z")

    def sign_up(credentials: dict) -> SimpleNamespace:
        calls.append(credentials)
        return SimpleNamespace(user=fake_user, session=_session())

    fake_client = SimpleNamespace(auth=SimpleNamespace(sign_up=sign_up))
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: fake_client)

    response = client.post(
        "/api/v1/auth/register",
        json=REGISTRATION,
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == "user-123"
    assert response.json()["access_token"] == "access-token"
    assert response.json()["email_confirmation_required"] is False
    assert "password" not in response.json()
    assert calls == [{"email": "worker@example.test", "password": "Safe-password9"}]


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
        json=REGISTRATION,
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
        json=REGISTRATION,
    )

    assert response.status_code == 400
    assert "An account already exists" in response.json()["detail"]


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


def test_registration_does_not_forward_client_roles_or_employee_metadata(monkeypatch) -> None:
    calls = []

    def sign_up(credentials):
        calls.append(credentials)
        return SimpleNamespace(user=SimpleNamespace(id="new-auth-user", email="worker@example.test"), session=None)

    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(sign_up=sign_up)))
    response = client.post("/api/v1/auth/register", json={
        **REGISTRATION, "email": "attacker@example.test",
        "role": "hr_admin", "employee_id": "other-employee", "data": {"role": "hr_admin"},
    })
    assert response.status_code == 201
    assert calls == [{"email": "worker@example.test", "password": "Safe-password9"}]
    assert "role" not in response.json()
    assert response.json()["email"] == INVITATION["email"]


def test_open_registration_without_invitation_is_rejected():
    response = client.post("/api/v1/auth/register", json={"email": "anyone@example.test", "password": "Safe-password9"})
    assert response.status_code == 422


@pytest.mark.parametrize("password", ["NoDigitsHere", "lowercase123", "Short1"])
def test_registration_enforces_password_rules(password):
    assert client.post("/api/v1/auth/register", json={**REGISTRATION, "password": password}).status_code == 422


def test_invalid_invitation_cannot_create_supabase_user(monkeypatch):
    def reject(*args, **kwargs):
        raise HTTPException(status_code=410, detail="Invitation has expired")
    monkeypatch.setattr(auth.invitations, "prepare", reject)
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace())
    assert client.post("/api/v1/auth/register", json=REGISTRATION).status_code == 410


def test_obfuscated_existing_user_does_not_consume_invitation(monkeypatch):
    completed = []
    monkeypatch.setattr(auth.invitations, "complete", lambda *args: completed.append(args))
    fake_user = SimpleNamespace(id="fake-obfuscated-id", email=INVITATION["email"])
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(
        sign_up=lambda data: SimpleNamespace(user=fake_user, session=None))))
    assert client.post("/api/v1/auth/register", json=REGISTRATION).status_code == 201
    assert completed == []


def test_session_without_confirmed_email_never_creates_profile(monkeypatch):
    completed = []
    monkeypatch.setattr(auth.invitations, "complete", lambda *args: completed.append(args))
    fake_user = SimpleNamespace(id="user-123", email=INVITATION["email"], email_confirmed_at=None, confirmed_at="phone-only")
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(
        sign_up=lambda data: SimpleNamespace(user=fake_user, session=_session()))))
    assert client.post("/api/v1/auth/register", json=REGISTRATION).status_code == 403
    assert completed == []


@pytest.mark.parametrize("token", ["123456", "12345678"])
def test_verify_otp_uses_invited_email_and_activates_only_verified_user(monkeypatch, token):
    calls, completed = [], []
    def verify(data):
        calls.append(data)
        return SimpleNamespace(user=SimpleNamespace(id="verified-user", email=INVITATION["email"], email_confirmed_at="now"), session=_session())
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(verify_otp=verify)))
    monkeypatch.setattr(auth.invitations, "complete", lambda *args: completed.append(args))
    response = client.post("/api/v1/auth/verify-registration", json={"invitation_code": REGISTRATION["invitation_code"], "token": token, "email": "attacker@example.test"})
    assert response.status_code == 200
    assert response.json()["access_token"] == "access-token"
    assert calls == [{"email": INVITATION["email"], "token": token, "type": "email"}]
    assert completed == [(REGISTRATION["invitation_code"], "verified-user")]


@pytest.mark.parametrize("token", ["12345", "1234567", "123456789"])
def test_registration_rejects_invalid_code_lengths_before_provider_call(monkeypatch, token):
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: pytest.fail("Must not consume OTP"))
    response = client.post("/api/v1/auth/verify-registration", json={
        "invitation_code": REGISTRATION["invitation_code"], "token": token,
    })
    assert response.status_code == 422 and token not in response.text
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])


def test_verification_returns_no_tokens_when_profile_creation_fails(monkeypatch):
    def conflict(*args):
        raise HTTPException(status_code=409, detail="An employee profile already exists. Contact HR")
    monkeypatch.setattr(auth.invitations, "complete", conflict)
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(verify_otp=lambda data:
        SimpleNamespace(user=SimpleNamespace(id="verified-user", email=INVITATION["email"], email_confirmed_at="now"), session=_session()))))
    response = client.post("/api/v1/auth/verify-registration", json={"invitation_code": REGISTRATION["invitation_code"], "token": "123456"})
    assert response.status_code == 409
    assert "access_token" not in response.json()


def test_completion_recovers_after_email_link_or_consumed_otp(monkeypatch):
    checked, completed = [], []
    def check(code, **kwargs):
        checked.append(kwargs)
        return INVITATION
    monkeypatch.setattr(auth.invitations, "check", check)
    monkeypatch.setattr(auth.invitations, "complete", lambda *args: completed.append(args))
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(sign_in_with_password=lambda data:
        SimpleNamespace(user=SimpleNamespace(id="verified-user", email=INVITATION["email"], email_confirmed_at="now"), session=_session()))))
    response = client.post("/api/v1/auth/complete-invitation", json={"invitation_code": REGISTRATION["invitation_code"], "email": INVITATION["email"], "password": "Safe-password9"})
    assert response.status_code == 200 and completed
    assert checked == [{"allow_consumed": True}]


def test_completion_rejects_different_email_before_auth(monkeypatch):
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: pytest.fail("Must not sign in a different email"))
    response = client.post("/api/v1/auth/complete-invitation", json={"invitation_code": REGISTRATION["invitation_code"], "email": "other@example.test", "password": "Safe-password9"})
    assert response.status_code == 403


def test_resend_uses_signup_type_and_preserves_provider_rate_limit(monkeypatch):
    from supabase_auth.errors import AuthApiError
    calls = []
    def resend(data):
        calls.append(data)
        raise AuthApiError("rate limited", 429, "over_email_send_rate_limit")
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(resend=resend)))
    response = client.post("/api/v1/auth/resend-registration", json={"invitation_code": REGISTRATION["invitation_code"]})
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"
    assert calls == [{"email": INVITATION["email"], "type": "signup"}]


def test_login_preserves_auth_rate_limit(monkeypatch):
    from supabase_auth.errors import AuthApiError
    def fail(data):
        raise AuthApiError("rate limited", 429, "over_request_rate_limit")
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: SimpleNamespace(auth=SimpleNamespace(sign_in_with_password=fail)))
    assert client.post("/api/v1/auth/login", json={"email": INVITATION["email"], "password": "Safe-password9"}).status_code == 429


def test_auth_validation_errors_do_not_echo_secrets():
    for path,payload,secret in [
        ("login",{"email": INVITATION["email"], "password": "Weak1"},"Weak1"),
        ("register",{**REGISTRATION,"password": "NoDigitsHere"},"NoDigitsHere"),
        ("verify-registration",{"invitation_code": REGISTRATION["invitation_code"],"token": "secret-otp"},"secret-otp")]:
        response = client.post("/api/v1/auth/"+path,json=payload)
        assert response.status_code == 422
        assert secret not in response.text
        assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])


def test_completion_supplies_names_only_after_verified_login(monkeypatch):
    completed = []
    monkeypatch.setattr(auth.invitations,"complete",lambda *args: completed.append(args))
    monkeypatch.setattr(auth,"get_supabase_auth_client",lambda: SimpleNamespace(auth=SimpleNamespace(sign_in_with_password=lambda data:
        SimpleNamespace(user=SimpleNamespace(id="verified-user",email=INVITATION["email"],email_confirmed_at="now"),session=_session()))))
    payload = {"invitation_code": REGISTRATION["invitation_code"],"email": INVITATION["email"],"password": "Safe-password9",
        "first_name": "  Алексей ","last_name": " Ким ","role": "hr_admin"}
    response = client.post("/api/v1/auth/complete-invitation",json=payload)
    assert response.status_code == 200
    assert completed == [(REGISTRATION["invitation_code"],"verified-user","Алексей","Ким")]
    assert "role" not in response.json()
    assert client.post("/api/v1/auth/complete-invitation",json={**payload,"first_name": "   "}).status_code == 422
