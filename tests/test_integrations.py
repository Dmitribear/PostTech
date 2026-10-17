import hashlib
import hmac
import json
import httpx
import pytest
from app.infrastructure.integrations import configuration, deliver, run_once

EVENT = {
    "id": "sample-id",
    "event_type": "request.approved",
    "payload": {"schema_version": 1, "request_id": "request-id"},
}


def test_disabled_worker_does_not_claim(monkeypatch):
    for prefix in ("INTEGRATION_1C", "INTEGRATION_DOCUMENTOLOG"):
        monkeypatch.delenv(prefix + "_ENABLED", raising=False)
    monkeypatch.setattr(
        "app.infrastructure.integrations.data_gateway",
        lambda: pytest.fail("No DB claims when disabled"),
    )
    assert run_once() == 0


def test_explicit_secure_configuration(monkeypatch):
    monkeypatch.setenv("INTEGRATION_1C_ENABLED", "true")
    monkeypatch.setenv("INTEGRATION_1C_SECRET", "s" * 32)
    for url in (
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test?key=secret",
    ):
        monkeypatch.setenv("INTEGRATION_1C_URL", url)
        assert configuration("1c") is None
    monkeypatch.setenv("INTEGRATION_1C_URL", "https://example.test/events")
    assert configuration("1c")


def test_signed_payload_stable_id_and_ack():
    calls = []
    secret = "s" * 32

    def handler(request):
        calls.append(request)
        stamp = request.headers["X-PostTech-Timestamp"]
        assert (
            request.headers["X-PostTech-Signature"]
            == "sha256="
            + hmac.new(
                secret.encode(), stamp.encode() + b"." + request.content, hashlib.sha256
            ).hexdigest()
        )
        assert (
            json.loads(request.content)["event_id"]
            == request.headers["Idempotency-Key"]
            == EVENT["id"]
        )
        return httpx.Response(200, json={"accepted": True, "event_id": EVENT["id"]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert deliver(EVENT, "https://example.test", secret, client) == (True, None)
        assert deliver(EVENT, "https://example.test", secret, client) == (True, None)
    assert len(calls) == 2 and calls[0].content == calls[1].content


@pytest.mark.parametrize(
    "status,body",
    [(200, {}), (202, {"accepted": True, "event_id": "wrong"}), (302, {}), (503, {})],
)
def test_no_false_delivery(status, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    ) as client:
        assert deliver(EVENT, "https://example.test", "s" * 32, client)[0] is False
