import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from supabase import ClientOptions, create_client
from supabase_auth.errors import AuthApiError, AuthRetryableError, AuthWeakPasswordError

from app.api.routes import auth
from app.main import app
from app.services import password_recovery


client = TestClient(app)
EMAIL = "worker@example.test"
CONFIRM = {"email": EMAIL, "token": "12345678", "password": "New-password9"}


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(password_recovery, "limiter", password_recovery.RecoveryLimiter())


def user(**overrides):
    return SimpleNamespace(**{"id": "employee-user", "email": EMAIL,
                             "email_confirmed_at": "2026-10-16T10:00:00Z", **overrides})


def recovery_response(account=None, session=True):
    account = account or user()
    return SimpleNamespace(user=account, session=SimpleNamespace(
        user=account, access_token="private-recovery-token", refresh_token="private-refresh-token") if session else None)


def fake_client(monkeypatch, verify=None, update=None, send=None, sign_out=None):
    actions = []
    fake = SimpleNamespace(auth=SimpleNamespace(
        reset_password_for_email=send or (lambda email: actions.append(("send", email))),
        verify_otp=verify or (lambda params: actions.append(("verify", params)) or recovery_response()),
        update_user=update or (lambda params: actions.append(("update", params)) or SimpleNamespace(user=user())),
        sign_out=sign_out or (lambda options: actions.append(("sign_out", options))),
    ))
    monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: fake)
    return actions


def test_reset_request_normalizes_address_and_does_not_return_identity_or_tokens(monkeypatch):
    actions = fake_client(monkeypatch)
    response = client.post("/api/v1/auth/password-reset", json={"email": " WORKER@example.test "})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"message": "If an account exists for this email, a password reset code will be sent", "retry_after": 60}
    assert actions == [("send", EMAIL)]


@pytest.mark.parametrize("code,status", [("user_not_found", 400), ("email_address_not_authorized", 400),
                                       ("over_email_send_rate_limit", 429), ("unexpected_failure", 500)])
def test_provider_account_and_delivery_errors_do_not_reveal_email_existence(monkeypatch, code, status):
    def send(_):
        raise AuthApiError("Secret provider diagnostics for " + EMAIL, status, code)
    fake_client(monkeypatch, send=send)
    response = client.post("/api/v1/auth/password-reset", json={"email": EMAIL})
    assert response.status_code == 200
    assert response.json()["retry_after"] == 60
    assert EMAIL not in response.text and "diagnostics" not in response.text


def test_send_cooldown_is_case_insensitive_and_independent_of_delivery(monkeypatch):
    actions = fake_client(monkeypatch)
    first = client.post("/api/v1/auth/password-reset", json={"email": EMAIL})
    second = client.post("/api/v1/auth/password-reset", json={"email": EMAIL.upper()})
    assert first.json() == second.json() and second.status_code == 200
    assert actions == [("send", EMAIL)]


def test_parallel_reset_requests_send_at_most_once(monkeypatch):
    actions = fake_client(monkeypatch)
    barrier = Barrier(4)
    def send(_):
        barrier.wait(timeout=3)
        return client.post("/api/v1/auth/password-reset", json={"email": EMAIL}).status_code
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(send, range(4))) == [200] * 4
    assert actions == [("send", EMAIL)]


def test_send_ip_limit_cannot_be_bypassed_by_changing_addresses(monkeypatch):
    actions = fake_client(monkeypatch)
    for n in range(10):
        assert client.post("/api/v1/auth/password-reset", json={"email": f"worker{n}@example.test"}).status_code == 200
    response = client.post("/api/v1/auth/password-reset", json={"email": "another@example.test"},
                           headers={"X-Forwarded-For": "1.2.3.4"})
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert len(actions) == 10


@pytest.mark.parametrize("token", ["123456", "12345678"])
def test_confirmation_uses_only_recovery_identity_and_returns_no_session(monkeypatch, token):
    actions = fake_client(monkeypatch)
    response = client.post("/api/v1/auth/password-reset/confirm", json={
        **CONFIRM, "token": token, "type": "email", "user_id": "victim", "access_token": "attacker-token", "role": "hr_admin"
    }, headers={"Authorization": "Bearer attacker-token"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"message": "Password updated. Sign in with your new password"}
    assert actions == [("verify", {"email": EMAIL, "token": token, "type": "recovery"}),
                       ("update", {"password": CONFIRM["password"]}), ("sign_out", {"scope": "global"})]
    assert "token" not in response.text and EMAIL not in response.text


@pytest.mark.parametrize("invalid", ["no_session", "no_user", "unconfirmed", "different_email", "different_session_user"])
def test_confirmation_never_updates_without_matching_confirmed_recovery_session(monkeypatch, invalid):
    verified = recovery_response()
    if invalid == "no_session": verified.session = None
    if invalid == "no_user": verified.user = None
    if invalid == "unconfirmed": verified.user.email_confirmed_at = None
    if invalid == "different_email": verified.user.email = "someone-else@example.test"
    if invalid == "different_session_user": verified.session.user = user(id="another-account")
    actions = fake_client(monkeypatch, verify=lambda _: verified,
                          update=lambda _: pytest.fail("Must not update password"))
    response = client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM)
    assert response.status_code == 400
    assert "invalid or expired" in response.json()["detail"]
    assert actions == ([] if invalid == "no_session" else [("sign_out", {"scope": "local"})])


def test_invalid_reused_or_expired_code_does_not_call_update(monkeypatch):
    consumed = False
    def verify(_):
        nonlocal consumed
        if consumed:
            raise AuthApiError("Internal OTP diagnostics", 403, "otp_expired")
        consumed = True
        return recovery_response()
    actions = fake_client(monkeypatch, verify=verify)
    assert client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM).status_code == 200
    retry = client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM)
    assert retry.status_code == 400 and retry.json() == {"detail": "Reset code is invalid or expired. Request a new code"}
    assert len([action for action in actions if action[0] == "update"]) == 1


def test_confirmation_bruteforce_limit_is_email_based(monkeypatch):
    calls = []
    def verify(_):
        calls.append(True)
        raise AuthApiError("Wrong OTP", 403, "otp_expired")
    fake_client(monkeypatch, verify=verify)
    for _ in range(5):
        assert client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM).status_code == 400
    limited = client.post("/api/v1/auth/password-reset/confirm", json={**CONFIRM, "email": EMAIL.upper()})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert len(calls) == 5


@pytest.mark.parametrize("password", ["NoDigitsHere", "lowercase123", "Short1"])
def test_weak_password_is_rejected_before_consuming_otp_and_not_echoed(monkeypatch, password):
    fake_client(monkeypatch, verify=lambda _: pytest.fail("Must not consume OTP"))
    response = client.post("/api/v1/auth/password-reset/confirm", json={**CONFIRM, "password": password})
    assert response.status_code == 422
    assert password not in response.text and CONFIRM["token"] not in response.text
    assert all("input" not in item and "ctx" not in item for item in response.json()["detail"])


@pytest.mark.parametrize("token", ["secret-token", "12345", "1234567", "123456789"])
def test_invalid_token_shape_is_rejected_without_echo(monkeypatch, token):
    fake_client(monkeypatch, verify=lambda _: pytest.fail("Must not consume OTP"))
    response = client.post("/api/v1/auth/password-reset/confirm", json={**CONFIRM, "token": token})
    assert response.status_code == 422 and token not in response.text


@pytest.mark.parametrize("provider_error", [True, False])
def test_update_failure_revokes_recovery_session_and_explains_new_code_needed(monkeypatch, provider_error):
    def update(_):
        if provider_error:
            raise AuthApiError("Sensitive provider detail", 400, "same_password")
        raise TimeoutError("Sensitive transport detail")
    actions = fake_client(monkeypatch, update=update)
    response = client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM)
    assert response.status_code == (400 if provider_error else 503)
    assert "request a new code" in response.json()["detail"]
    assert "Sensitive" not in response.text
    assert actions[-1] == ("sign_out", {"scope": "local"})


def test_success_is_not_reported_as_failure_if_session_cleanup_is_unavailable(monkeypatch):
    def sign_out(_):
        raise TimeoutError("Private transport failure")
    fake_client(monkeypatch, sign_out=sign_out)
    response = client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM)
    assert response.status_code == 200 and "Password updated" in response.json()["message"]


def test_provider_weak_password_error_is_a_recoverable_policy_failure(monkeypatch):
    def update(_):
        raise AuthWeakPasswordError("Provider private reasons", 422, ["pwned"])
    actions = fake_client(monkeypatch, update=update)
    response = client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM)
    assert response.status_code == 400
    assert "different password and request a new code" in response.json()["detail"]
    assert "private" not in response.text and "pwned" not in response.text
    assert actions[-1] == ("sign_out", {"scope": "local"})


def test_retryable_email_failure_is_not_swallowed_as_an_account_error(monkeypatch):
    def send(_):
        raise AuthRetryableError("Private network diagnostics", 503)
    fake_client(monkeypatch, send=send)
    response = client.post("/api/v1/auth/password-reset", json={"email": EMAIL})
    assert response.status_code == 503
    assert response.json() == {"detail": "Supabase Auth is temporarily unavailable"}


def test_cooldown_expires_and_limiter_is_bounded_without_storing_pii(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(password_recovery, "monotonic", lambda: now[0])
    limiter = password_recovery.RecoveryLimiter(max_entries=2)
    assert limiter.allow_send(EMAIL, "127.0.0.1")
    assert not limiter.allow_send(EMAIL, "127.0.0.1")
    now[0] += 61
    assert limiter.allow_send(EMAIL, "127.0.0.1")
    assert not limiter.allow_send("other@example.test", "127.0.0.1")
    assert len(limiter._entries) == 2
    assert all(isinstance(key, bytes) and len(key) == 32 for key in limiter._entries)


def test_real_sdk_uses_verified_recovery_jwt_for_update_and_discards_session(monkeypatch):
    requests = []
    account = {"id": "a83f486c-a376-4b8e-a9ef-bb2114247bc1", "aud": "authenticated",
               "role": "authenticated", "email": EMAIL, "email_confirmed_at": "2026-10-16T10:00:00Z",
               "app_metadata": {}, "user_metadata": {}, "created_at": "2026-10-16T10:00:00Z"}
    def handle(request):
        requests.append(request)
        if request.url.path.endswith("/verify"):
            assert json.loads(request.content)["type"] == "recovery"
            return httpx.Response(200, json={"access_token": "verified-recovery-jwt", "refresh_token": "private-refresh",
                "token_type": "bearer", "expires_in": 3600, "user": account})
        if request.url.path.endswith("/user"):
            assert request.headers["authorization"] == "Bearer verified-recovery-jwt"
            assert json.loads(request.content) == {"password": CONFIRM["password"]}
            return httpx.Response(200, json=account)
        assert request.url.path.endswith("/logout")
        assert request.url.params["scope"] == "global"
        assert request.headers["authorization"] == "Bearer verified-recovery-jwt"
        return httpx.Response(204)
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        public = create_client("https://project.supabase.co", "sb_publishable_test_public", options=ClientOptions(
            httpx_client=transport, persist_session=False, auto_refresh_token=False, flow_type="implicit"))
        monkeypatch.setattr(auth, "get_supabase_auth_client", lambda: public)
        response = client.post("/api/v1/auth/password-reset/confirm", json=CONFIRM,
                               headers={"Authorization": "Bearer attacker-jwt"})
        assert response.status_code == 200
        assert public.auth.get_session() is None
    assert [request.method for request in requests] == ["POST", "PUT", "POST"]


def test_parallel_real_sdk_recoveries_keep_passwords_in_their_own_sessions(monkeypatch):
    from app.db import supabase
    verified_together = Barrier(2)
    updates = []
    accounts = {
        f"worker{n}@example.test": {"id": f"a83f486c-a376-4b8e-a9ef-bb2114247bc{n}",
            "aud": "authenticated", "role": "authenticated", "email": f"worker{n}@example.test",
            "email_confirmed_at": "2026-10-16T10:00:00Z", "created_at": "2026-10-16T10:00:00Z",
            "app_metadata": {}, "user_metadata": {}}
        for n in (1, 2)
    }
    def handle(request):
        if request.url.path.endswith("/verify"):
            account = accounts[json.loads(request.content)["email"]]
            verified_together.wait(timeout=5)
            return httpx.Response(200, json={"access_token": account["email"], "refresh_token": "private-refresh",
                "token_type": "bearer", "expires_in": 3600, "user": account})
        account = accounts[request.headers["authorization"].removeprefix("Bearer ")]
        if request.url.path.endswith("/user"):
            updates.append((account["email"], json.loads(request.content)["password"]))
            return httpx.Response(200, json=account)
        assert request.url.path.endswith("/logout")
        return httpx.Response(204)
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        pooled = create_client("https://project.supabase.co", "sb_publishable_test_public", options=ClientOptions(
            httpx_client=transport, persist_session=False, auto_refresh_token=False, flow_type="implicit"))
        monkeypatch.setattr(supabase, "get_supabase_auth_client", lambda: pooled)
        monkeypatch.setattr(auth, "get_supabase_auth_client", supabase.create_supabase_auth_client)
        def confirm(n):
            return client.post("/api/v1/auth/password-reset/confirm", json={
                "email": f"worker{n}@example.test", "token": "123456", "password": f"New-password{n}"}).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert list(executor.map(confirm, (1, 2))) == [200, 200]
        assert pooled.auth.get_session() is None
    assert sorted(updates) == [("worker1@example.test", "New-password1"), ("worker2@example.test", "New-password2")]
