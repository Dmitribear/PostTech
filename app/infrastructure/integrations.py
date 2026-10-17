"""At-least-once delivery. Receiver MUST deduplicate event_id before side effects.

No request comments or credentials are persisted in the outbound payload/logs.
A 2xx alone isn't an acknowledgement: the receiver returns accepted + event_id.
"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlparse

import httpx

from app.application.use_cases.academy import data_gateway, execute_query


def configuration(destination: str):
    prefix = {"1c": "INTEGRATION_1C", "documentolog": "INTEGRATION_DOCUMENTOLOG"}[
        destination
    ]
    url, secret = os.getenv(prefix + "_URL", ""), os.getenv(prefix + "_SECRET", "")
    parsed = urlparse(url)
    if os.getenv(prefix + "_ENABLED", "").lower() != "true":
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(secret) < 32
    ):
        return None
    return url, secret


def configured_destinations():
    return {d: configuration(d) is not None for d in ("1c", "documentolog")}


def deliver(
    event: dict, url: str, secret: str, client: httpx.Client
) -> tuple[bool, str | None]:
    body = json.dumps(
        {
            "event_id": event["id"],
            "event_type": event["event_type"],
            "payload": event["payload"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    try:
        response = client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": event["id"],
                "X-PostTech-Timestamp": timestamp,
                "X-PostTech-Signature": "sha256=" + signature,
            },
            timeout=15,
            follow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            return False, f"HTTP {response.status_code}"
        ack = response.json()
        if (
            not isinstance(ack, dict)
            or ack.get("event_id") != event["id"]
            or ack.get("accepted") is not True
        ):
            return False, "Invalid acknowledgement"
        return True, None
    except (httpx.HTTPError, ValueError):
        return False, "Network error or invalid acknowledgement"


def run_once() -> int:
    processed = 0
    with httpx.Client() as client:
        for destination in ("1c", "documentolog"):
            config = configuration(destination)
            if not config:
                continue
            event = execute_query(
                data_gateway().rpc(
                    "claim_integration_event", {"p_destination": destination}
                )
            )
            if not event:
                continue
            ok, detail = deliver(event, *config, client)
            execute_query(
                data_gateway().rpc(
                    "finish_integration_event",
                    dict(
                        p_id=event["id"],
                        p_token=event["lease_token"],
                        p_success=ok,
                        p_error=detail,
                    ),
                )
            )
            processed += 1
    return processed
