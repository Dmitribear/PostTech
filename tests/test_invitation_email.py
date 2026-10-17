from app.domain.errors import ApplicationError
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.infrastructure.config import Settings
from app.application.dto.auth import RegistrationRequest
from app.infrastructure import invitation_email as mail
from app.application.use_cases import invitations

INVITE = {
    "id": "invite-1",
    "email": "employee@example.test",
    "role": "manager",
    "department": "<script>unsafe</script>",
    "expires_at": "2026-12-01T12:00:00+00:00",
}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(
        mail,
        "get_settings",
        lambda: SimpleNamespace(
            resend_api_key=SecretStr("test-secret"),
            invitation_email_from="PostTech <onboarding@resend.dev>",
            portal_public_url=None,
        ),
    )


def test_email_contains_hr_role_and_code_without_password(monkeypatch):
    def post(url, **kwargs):
        payload = kwargs["json"]
        assert payload["to"] == [INVITE["email"]]
        assert "Руководитель" in payload["text"] and "JP-test-code" in payload["text"]
        assert "<script>" not in payload["html"]
        assert "&lt;script&gt;" in payload["html"]
        assert kwargs["headers"]["Idempotency-Key"] == "invitation/invite-1/hash"
        assert "test-secret" not in str(payload)
        return httpx.Response(200, json={"id": "message-id"})

    monkeypatch.setattr(mail.httpx, "post", post)
    assert mail.send(INVITE, "JP-test-code", "hash") == "accepted"


@pytest.mark.parametrize(
    "status,expected",
    [(403, "failed"), (429, "failed"), (500, "unknown"), (200, "unknown")],
)
def test_provider_rejection_is_not_success(monkeypatch, status, expected):
    monkeypatch.setattr(
        mail.httpx, "post", lambda *a, **k: httpx.Response(status, json={})
    )
    assert mail.send(INVITE, "JP-test", "hash") == expected


def test_timeout_is_unknown_not_false_success(monkeypatch):
    def timeout(*a, **kw):
        raise httpx.ReadTimeout("secret in provider error")

    monkeypatch.setattr(mail.httpx, "post", timeout)
    assert mail.send(INVITE, "JP-test", "hash") == "unknown"


def test_worker_cannot_send_or_rotate(monkeypatch):
    monkeypatch.setattr(invitations, "_rpc", lambda *a: pytest.fail("Unauthorized RPC"))
    with pytest.raises((HTTPException, ApplicationError)) as error:
        invitations.resend(SimpleNamespace(id="worker", role="worker"), "invite-1")
    assert error.value.status_code == 403


def test_unconfigured_sender_never_rotates_code(monkeypatch):
    monkeypatch.setattr(mail, "configured", lambda: False)
    monkeypatch.setattr(
        invitations, "_rpc", lambda *a: pytest.fail("Code must not rotate")
    )
    with pytest.raises((HTTPException, ApplicationError)) as error:
        invitations.resend(SimpleNamespace(id="hr", role="hr_admin"), "invite-1")
    assert error.value.status_code == 503


def test_retry_uses_database_recipient_and_role(monkeypatch):
    calls = []

    def rpc(name, params):
        calls.append((name, params))
        return INVITE if name == "begin_invitation_email" else {"recorded": True}

    monkeypatch.setattr(invitations, "_rpc", rpc)
    monkeypatch.setattr(
        mail,
        "send",
        lambda invite, code, digest: "accepted" if invite is INVITE else pytest.fail(),
    )
    result = invitations.resend(SimpleNamespace(id="hr", role="hr_admin"), "invite-1")
    assert result["role"] == "manager" and result["email"] == INVITE["email"]
    assert calls[0][1]["p_token_hash"] == invitations.code_hash(
        result["invitation_code"]
    )
    assert calls[1][1]["p_status"] == "accepted"


def test_registration_cannot_submit_role():
    with pytest.raises(ValidationError):
        RegistrationRequest(
            invitation_code="JP-test-code",
            first_name="Test",
            last_name="User",
            password="Test-password9",
            role="hr_admin",
        )


def test_empty_compose_public_url_is_valid():
    assert Settings(_env_file=None, portal_public_url="").portal_public_url is None
