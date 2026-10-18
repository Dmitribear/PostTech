from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from pydantic import SecretStr
from postgrest.exceptions import APIError
import pytest

from app.presentation.http import security
from app.infrastructure.config import Settings
from app.main import app
from app.domain.models import UserContext
from app.infrastructure import telegram

ACTOR = UserContext(id=str(uuid4()), auth_user_id=str(uuid4()), role="worker")
SECRET = "test-worker-secret-not-a-real-secret-0123456789"


@pytest.fixture
def configured(monkeypatch):
    settings = Settings(_env_file=None, telegram_worker_secret=SecretStr(SECRET), telegram_bot_username="PostTechTestBot")
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    monkeypatch.setattr(telegram, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def client(configured):
    with TestClient(app) as c:
        yield c


def test_issue_saves_only_hash_and_rotates_random_code(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "_rpc", lambda n,p: calls.append((n,p)) or {"expires_at":"2026-12-01T12:00:00Z"})
    first, second = telegram.issue_link(ACTOR), telegram.issue_link(ACTOR)
    assert first["url"] != second["url"]
    import hashlib
    for result, (name, args) in zip((first, second), calls):
        code = result["url"].split("?start=")[1]
        assert len(code) == 43 and name == "issue_telegram_link"
        assert args == {"p_actor_id": ACTOR.id, "p_code_hash": hashlib.sha256(code.encode()).hexdigest()}
        assert code not in str(args) and SECRET not in str(result)


def test_api_needs_no_bot_token(configured):
    configured.telegram_bot_token = None
    assert telegram.configured()


@pytest.mark.parametrize("secret", [None, SecretStr("short")])
def test_disabled_worker_fails_closed(configured, secret):
    configured.telegram_worker_secret = secret
    assert not telegram.configured()
    with pytest.raises(HTTPException) as error:
        security.require_telegram_worker(SECRET)
    assert error.value.status_code == 503


@pytest.mark.parametrize("name", ["wrong", "bad/name_bot", "evil.example/bot", "a"*40+"bot"])
def test_invalid_bot_name_not_linked(configured, name):
    configured.telegram_bot_username = name
    assert telegram.bot_username() is None and not telegram.configured()


@pytest.mark.parametrize("path,method,data", [
    ("consume-link","post",{"code":"x"*43,"telegram_user_id":123,"chat_id":123}),
    ("outbox","get",None), ("worker-state","get",None),
    ("worker-state","patch",{"offset":123}),
    (f"outbox/{uuid4()}/ack","post",{"lease_token":str(uuid4()),"status":"sent"}),
])
def test_worker_endpoints_reject_public_and_bad_secret(client, path, method, data, monkeypatch):
    monkeypatch.setattr(telegram, "_rpc", lambda *a: pytest.fail("No unauthenticated RPC"))
    for headers in ({}, {"X-Telegram-Worker-Key":"invalid"}, {"Authorization":"Bearer website-session"}):
        response = client.request(method, f"/api/v1/telegram/{path}", json=data, headers=headers)
        assert response.status_code == 401


def test_worker_cannot_mint_website_link(client, monkeypatch):
    monkeypatch.setattr(telegram, "_rpc", lambda *a: pytest.fail("Worker cannot mint linking code"))
    response = client.post("/api/v1/telegram/link", headers={"X-Telegram-Worker-Key":SECRET,"X-Telegram-User-Id":"123"})
    assert response.status_code == 401


def test_consume_private_chat_only_and_forbid_actor_spoof(client, monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "_rpc", lambda n,p: calls.append((n,p)) or {"linked":True})
    headers = {"X-Telegram-Worker-Key":SECRET}
    payload = {"code":"x"*43,"telegram_user_id":123,"chat_id":123,"username":"alice"}
    for bad in ({"chat_id":-123}, {"chat_id":124}, {"telegram_user_id":True}, {"employee_id":ACTOR.id}, {"username":"@abc"}):
        assert client.post("/api/v1/telegram/consume-link",json=payload|bad,headers=headers).status_code == 422
    assert not calls
    assert client.post("/api/v1/telegram/consume-link",json=payload,headers=headers).status_code == 200
    assert "code" not in calls[0][1] and len(calls[0][1]["p_code_hash"]) == 64


def test_worker_uses_fresh_hr_role_every_request(configured, monkeypatch):
    role = {"value":"worker"}
    calls = []
    def rpc(name, params):
        calls.append((name,params))
        return {**ACTOR.model_dump(),"role":role["value"]}
    monkeypatch.setattr(telegram, "_rpc", rpc)
    assert security.get_current_user(None, SECRET, "123").role == "worker"
    role["value"] = "manager"
    assert security.get_current_user(None, SECRET, "123").role == "manager"
    assert calls == [("resolve_telegram_actor",{"p_telegram_user_id":123})]*2


@pytest.mark.parametrize("user", [None,"-1","0","abc","١٢٣",str(2**63),"1"*5000])
def test_worker_identity_invalid(configured, monkeypatch, user):
    monkeypatch.setattr(telegram, "_rpc", lambda *a: pytest.fail("Invalid identity cannot be queried"))
    with pytest.raises(HTTPException) as error:
        security.get_current_user(None, SECRET, user)
    assert error.value.status_code == 401


def test_untrusted_identity_header_cannot_fall_back_to_bearer(configured, monkeypatch):
    monkeypatch.setattr(security, "get_supabase_client", lambda: pytest.fail("Do not fall back to bearer"))
    with pytest.raises(HTTPException) as error:
        security.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials="session"),None,"123")
    assert error.value.status_code == 401


def test_existing_team_api_keeps_role_checks_for_telegram(client, monkeypatch):
    monkeypatch.setattr(telegram, "_rpc", lambda n,p: ACTOR.model_dump())
    response = client.get("/api/v1/team",headers={"X-Telegram-Worker-Key":SECRET,"X-Telegram-User-Id":"123"})
    assert response.status_code == 403


def test_worker_offset_scoped_by_bot_identity(client, monkeypatch):
    calls=[]
    def rpc(name,params):
        calls.append((name,params))
        return {"bot_id":params["p_bot_id"],"offset":params["p_offset"] or 0}
    monkeypatch.setattr(telegram,"_rpc",rpc)
    headers={"X-Telegram-Worker-Key":SECRET}
    assert client.get('/api/v1/telegram/worker-state',headers=headers).status_code==422
    assert client.get('/api/v1/telegram/worker-state?bot_id=321',headers=headers).json()=={"bot_id":321,"offset":0}
    assert client.patch('/api/v1/telegram/worker-state',headers=headers,json={"bot_id":321,"offset":456}).json()=={"bot_id":321,"offset":456}
    assert calls==[("telegram_worker_offset",{"p_bot_id":321,"p_offset":None}),
                   ("telegram_worker_offset",{"p_bot_id":321,"p_offset":456})]


def test_unlinked_identity_rejected_by_existing_api(client, monkeypatch):
    def revoked(*args):
        raise HTTPException(status_code=403,detail="Telegram account is not linked")
    monkeypatch.setattr(telegram,"resolve_actor",revoked)
    response=client.get("/api/v1/profile",headers={"X-Telegram-Worker-Key":SECRET,"X-Telegram-User-Id":"123"})
    assert response.status_code==403


def test_website_status_settings_unlink_and_cache(client, monkeypatch):
    app.dependency_overrides[security.get_current_user] = lambda: ACTOR
    app.dependency_overrides[security.get_website_user] = lambda: ACTOR
    calls = []
    def rpc(name, params):
        calls.append((name,params))
        if name == "issue_telegram_link": return {"expires_at":"2026-12-01T12:00:00Z"}
        return {"linked":True,"telegram_username":"alice","notifications_enabled":False}
    monkeypatch.setattr(telegram, "_rpc", rpc)
    try:
        status = client.get("/api/v1/telegram/status")
        assert status.json() == {"enabled":True,"linked":True,"telegram_username":"alice","notifications_enabled":False,"bot_username":"PostTechTestBot","link_id":None}
        assert SECRET not in status.text
        link = client.post("/api/v1/telegram/link")
        assert link.status_code == 200 and link.headers["cache-control"] == "no-store"
        assert client.patch("/api/v1/telegram/settings",json={"notifications_enabled":False}).status_code == 200
        assert client.delete("/api/v1/telegram/link").status_code == 200
        assert ("set_telegram_settings",{"p_actor_id":ACTOR.id,"p_notifications_enabled":False}) in calls
        assert ("unlink_telegram",{"p_actor_id":ACTOR.id}) in calls
    finally:
        app.dependency_overrides.pop(security.get_current_user,None)
        app.dependency_overrides.pop(security.get_website_user,None)


def test_database_failures_do_not_leak_credentials(monkeypatch):
    def fail():
        raise APIError({"code":"PGRST202","message":"secret database detail","details":None,"hint":None})
    monkeypatch.setattr(telegram,"get_supabase_client",fail)
    with pytest.raises(HTTPException) as error:
        telegram._rpc("telegram_status",{})
    assert error.value.status_code == 503 and "secret" not in error.value.detail
