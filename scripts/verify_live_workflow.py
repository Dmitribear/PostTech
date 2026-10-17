"""Verify one synthetic leave request against the running, real-backed API.

Uses only Python's standard library. Secrets stay in memory and an optional
ignored credentials file; neither HTTP bodies nor tokens are printed.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parents[1]
LOCAL_TIME = timezone(timedelta(hours=5))  # User's Asia/Qyzylorda date.
SEED = {
    "employee": ("employee@posttech.demo", "worker", "DEMO-EMP-001"),
    "manager": ("manager@posttech.demo", "manager", "DEMO-MGR-001"),
}


class VerificationError(Exception):
    """Only fixed, nonsecret diagnostic messages belong in this exception."""


def require(condition: Any, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def now() -> str:
    return datetime.now(UTC).isoformat()


def valid_uuid(value: Any) -> bool:
    try:
        return str(UUID(str(value))) == value
    except (ValueError, TypeError, AttributeError):
        return False


def timestamp(value: Any) -> datetime:
    require(isinstance(value, str), "A response timestamp is missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError("A response timestamp is invalid") from exc
    require(result.tzinfo is not None, "A response timestamp has no timezone")
    return result


def ignored_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    require(path.is_relative_to(ROOT), "Runtime files must be inside this repository")
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(path)], cwd=ROOT,
            capture_output=True, check=False,
        )
    except OSError as exc:
        raise VerificationError("Git is required to verify runtime files are ignored") from exc
    require(result.returncode == 0, "Runtime files must be Git-ignored before this check")
    return path


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise VerificationError("A local JSON file cannot be read") from exc
    require(isinstance(value, dict), "A local JSON file must contain an object")
    return value


def credentials(path: Path) -> dict[str, dict[str, str]]:
    saved = read_json(path) if path.exists() else {}
    result = {}
    for actor, (email, _, _) in SEED.items():
        entry = saved.get(actor, {})
        require(isinstance(entry, dict), "A credentials entry is invalid")
        actor_email = os.environ.get(f"POSTTECH_{actor.upper()}_EMAIL", entry.get("email", email))
        password = os.environ.get(f"POSTTECH_{actor.upper()}_PASSWORD", entry.get("password"))
        require(isinstance(actor_email, str) and actor_email.endswith("@posttech.demo"),
                "Only fictional @posttech.demo accounts may run this check")
        require(isinstance(password, str) and password, f"Missing {actor} password")
        result[actor] = {"email": actor_email, "password": password}
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials or bearer tokens to another URL.


class API:
    def __init__(self, base: str):
        parsed = urlsplit(base)
        require(parsed.scheme in ("http", "https"), "API URL must use HTTP or HTTPS")
        require(parsed.hostname in ("127.0.0.1", "localhost", "::1"), "API URL must be loopback")
        require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
                "API URL cannot contain credentials, query, or fragment")
        require(parsed.path in ("", "/", "/api/v1", "/api/v1/"), "Use the API origin or /api/v1 base")
        self.base = base.rstrip("/")
        if not self.base.endswith("/api/v1"):
            self.base += "/api/v1"
        self.opener = build_opener(NoRedirect)
        self.tokens: dict[str, str] = {}
        self.calls = 0

    def call(self, method: str, path: str, actor: str | None = None,
             body: dict | None = None, expected: int = 200, key: str | None = None) -> Any:
        headers = {"Accept": "application/json"}
        if actor is not None:
            headers["Authorization"] = "Bearer " + self.tokens[actor]
        if body is not None:
            headers["Content-Type"] = "application/json"
        if key is not None:
            headers["Idempotency-Key"] = key
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        self.calls += 1
        try:
            response = self.opener.open(request, timeout=30)
        except HTTPError as exc:
            response = exc
        except (URLError, TimeoutError, OSError) as exc:
            raise VerificationError("API connection failed; rerun with the same checkpoint") from exc
        with response:
            status = response.status
            # Do not include a server body: it can contain credentials or PII.
            require(status == expected,
                    f"{method} {path.split('?')[0]} returned HTTP {status}; expected {expected}")
            if expected >= 400:
                return None
            try:
                return json.loads(response.read())
            except (ValueError, OSError) as exc:
                raise VerificationError("API returned unreadable JSON") from exc

    def rows(self, path: str, actor: str, **query: str) -> list[dict]:
        rows: list[dict] = []
        for offset in range(0, 100_000, 100):
            page = self.call("GET", path + "?" + urlencode({**query, "limit": 100, "offset": offset}), actor)
            require(isinstance(page, list) and all(isinstance(row, dict) for row in page),
                    "API list response has an unexpected shape")
            rows.extend(page)
            if len(page) < 100:
                return rows
        raise VerificationError("API pagination exceeded the verification limit")


def preflight(api: API, accounts: dict) -> dict[str, str]:
    api.call("GET", "/profile", expected=401)
    identities = {}
    for actor, (_, role, employee_code) in SEED.items():
        session = api.call("POST", "/auth/login", body=accounts[actor])
        require(isinstance(session, dict) and valid_uuid(session.get("user_id")), "Login user ID is missing")
        require(isinstance(session.get("access_token"), str) and session["access_token"], "Login token is missing")
        api.tokens[actor] = session["access_token"]
        identities[actor + "_auth_id"] = session["user_id"]
        profile = api.call("GET", "/profile", actor)
        require(isinstance(profile, dict) and valid_uuid(profile.get("id")), "Profile ID is missing")
        code = profile.get("employee_code", "")
        prefix = "LIVE-EMP-" if actor == "employee" else "LIVE-MGR-"
        seeded = profile.get("external_source") == "mock-1c-zup" and code == employee_code
        dedicated = (profile.get("external_source") == "posttech-live-check"
                     and isinstance(code, str) and code.startswith(prefix) and len(code) > len(prefix))
        require(profile.get("role") == role and (seeded or dedicated)
                and profile.get("email") == accounts[actor]["email"],
                f"The {actor} profile is not an expected fictional test profile")
        identities[actor + "_id"] = profile["id"]
        if actor == "employee":
            identities["assigned_manager_id"] = profile.get("manager_id")
    require(identities["employee_id"] != identities["manager_id"], "Actors must be different profiles")
    require(identities["employee_auth_id"] != identities["manager_auth_id"], "Actors must be different Auth users")
    require(identities.pop("assigned_manager_id") == identities["manager_id"], "Employee has a different manager")
    team = api.call("GET", "/team", "manager")
    require(isinstance(team, list), "Team response has an unexpected shape")
    members = [row for row in team if isinstance(row, dict) and row.get("id") == identities["employee_id"]]
    require(len(members) == 1 and members[0].get("manager_id") == identities["manager_id"],
            "The demo employee is not in the manager's team")
    # Verify list tables are accessible before any workflow mutation.
    for actor in SEED:
        api.call("GET", "/requests?limit=1", actor)
        api.call("GET", "/notifications?limit=1", actor)
    return identities


@contextmanager
def checkpoint_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise VerificationError("Checkpoint is locked; ensure no check is running before removing its .lock file") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def save_checkpoint(path: Path, state: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def prepare_state(path: Path, api: API, actors: dict, start: str | None) -> dict:
    if path.exists():
        state = read_json(path)
        require(state.get("version") == 1 and state.get("api_base") == api.base
                and state.get("actors") == actors, "Checkpoint targets a different API or actors")
        require(valid_uuid(state.get("run_id")), "Checkpoint run ID is invalid")
        require(not state.get("request_id") or valid_uuid(state["request_id"]), "Checkpoint request ID is invalid")
        require(start is None or state.get("start_date") == start, "Checkpoint dates cannot be changed")
        timestamp(state.get("started_at"))
        try:
            start_date = date.fromisoformat(state["start_date"])
            end_date = date.fromisoformat(state["end_date"])
        except (KeyError, ValueError, TypeError) as exc:
            raise VerificationError("Checkpoint dates are invalid") from exc
        require(end_date == start_date + timedelta(days=1), "Checkpoint date range is invalid")
        return state
    try:
        start_date = date.fromisoformat(start) if start else datetime.now(LOCAL_TIME).date() + timedelta(days=30)
    except ValueError as exc:
        raise VerificationError("Start date must use YYYY-MM-DD") from exc
    state = {
        "version": 1, "api_base": api.base, "run_id": str(uuid4()), "actors": actors,
        "start_date": start_date.isoformat(), "end_date": (start_date + timedelta(days=1)).isoformat(),
        "started_at": now(), "request_id": None,
    }
    # Persist the key before sending POST, including if its response is lost.
    save_checkpoint(path, state)
    return state


def verify_request(row: dict, state: dict, payload: dict) -> None:
    require(isinstance(row, dict) and valid_uuid(row.get("id")), "Request ID is missing")
    require(not state.get("request_id") or row["id"] == state["request_id"], "Create retry returned a different request")
    require(row.get("employee_id") == state["actors"]["employee_id"]
            and all(row.get(key) == value for key, value in payload.items())
            and row.get("amount") is None, "Request fields do not match the synthetic submission")
    require(row.get("status") in ("pending", "approved"), "Synthetic request has an unexpected status")
    timestamp(row.get("created_at"))
    timestamp(row.get("updated_at"))


def snapshot(api: API, state: dict, approved: bool) -> dict:
    request_id, actors = state["request_id"], state["actors"]
    history = api.call("GET", f"/requests/{request_id}/history", "employee")
    expected = ["created", "approved"] if approved else ["created"]
    require(isinstance(history, list) and [event.get("event_type") for event in history] == expected,
            "History contains missing, duplicate, or unexpected transitions")
    previous_time = None
    for index, event in enumerate(history):
        require(valid_uuid(event.get("id")) and event.get("request_id") == request_id
                and event.get("actor_id") == actors["manager_id" if index else "employee_id"]
                and event.get("from_status") == ("pending" if index else None)
                and event.get("to_status") == ("approved" if index else "pending"),
                "History actor or status transition is wrong")
        event_time = timestamp(event.get("created_at"))
        require(previous_time is None or event_time >= previous_time, "History timestamps are not chronological")
        previous_time = event_time
    notifications = {}
    for actor, expected_type in (("manager", "request_created"), ("employee", "request_status_changed")):
        rows = api.rows("/notifications", actor, request_id=request_id)
        require(len(rows) == (1 if actor == "manager" or approved else 0),
                f"Unexpected {actor} notification count")
        for row in rows:
            require(valid_uuid(row.get("id")) and row.get("employee_id") == actors[actor + "_id"]
                    and row.get("request_id") == request_id and row.get("notification_type") == expected_type,
                    "Notification owner, request, or type is wrong")
            timestamp(row.get("created_at"))
        notifications[actor] = rows
    return {"history": history, "notifications": notifications}


def workflow(api: API, path: Path, actors: dict, start: str | None) -> dict:
    with checkpoint_lock(path):
        state = prepare_state(path, api, actors, start)
        payload = {
            "request_type": "leave", "start_date": state["start_date"], "end_date": state["end_date"],
            "comment": f"[SYNTHETIC LIVE CHECK {state['run_id']}] Тестовая заявка; не кадровое поручение.",
        }
        review = {"status": "approved", "reviewer_comment": f"[SYNTHETIC LIVE CHECK {state['run_id']}] Тестовое согласование."}
        created = api.call("POST", "/requests", "employee", payload, expected=201, key=state["run_id"])
        verify_request(created, state, payload)
        require(state.get("request_id") or created["status"] == "pending",
                "A newly created request must be pending")
        state["request_id"] = created["id"]
        save_checkpoint(path, state)
        request_path = f"/requests/{state['request_id']}"
        before = snapshot(api, state, created["status"] == "approved")
        replay = api.call("POST", "/requests", "employee", payload, expected=201, key=state["run_id"])
        require(replay == created, "Create retry changed the request")
        require(snapshot(api, state, created["status"] == "approved") == before,
                "Create retry changed history or notifications")
        # A worker's own decision must be rejected without side effects.
        api.call("PATCH", request_path + "/review", "employee", review, expected=403)
        require(api.call("GET", request_path, "employee") == created
                and snapshot(api, state, created["status"] == "approved") == before,
                "Denied employee review changed workflow data")
        for actor in SEED:
            rows = api.rows("/requests", actor, employee_id=actors["employee_id"], request_type="leave")
            matching = [row for row in rows if row.get("comment") == payload["comment"]]
            require(len(matching) == 1 and matching[0]["id"] == state["request_id"],
                    "Synthetic request is absent or duplicated in a visible list")
        approved = api.call("PATCH", request_path + "/review", "manager", review)
        verify_request(approved, state, payload)
        require(approved.get("status") == "approved" and approved.get("reviewed_by") == actors["manager_id"]
                and approved.get("reviewer_comment") == review["reviewer_comment"], "Manager approval was not stored")
        require(timestamp(approved.get("reviewed_at")) >= timestamp(approved["created_at"]),
                "Approval predates request creation")
        decided = snapshot(api, state, True)
        require(api.call("PATCH", request_path + "/review", "manager", review) == approved,
                "Review retry changed the request or decision timestamp")
        require(snapshot(api, state, True) == decided, "Review retry changed history or notifications")
        require(api.call("GET", request_path, "employee") == approved,
                "Employee cannot see the approved decision")
        require(api.call("GET", request_path + "/history", "manager") == decided["history"],
                "Manager and employee see different history")
        notification = decided["notifications"]["employee"][0]
        notification_path = f"/notifications/{notification['id']}/read"
        read = api.call("POST", notification_path, "employee")
        timestamp(read.get("read_at"))
        require({key: value for key, value in read.items() if key != "read_at"}
                == {key: value for key, value in notification.items() if key != "read_at"},
                "Notification reading changed fields other than read_at")
        require(api.call("POST", notification_path, "employee") == read, "Notification read retry changed first-read time")
        require(not api.rows("/notifications", "employee", request_id=state["request_id"], unread_only="true"),
                "Read notification remains in the unread list")
        final = snapshot(api, state, True)
        require(final["history"] == decided["history"], "Notification reading changed request history")
        summary = {
            "status": "passed", "request_id": state["request_id"], **actors,
            "request_status": approved["status"], "started_at": state["started_at"],
            "verified_at": now(), "created_at": approved["created_at"],
            "reviewed_at": approved["reviewed_at"], "notification_read_at": read["read_at"],
            "history_count": len(final["history"]),
            "manager_notification_count": len(final["notifications"]["manager"]),
            "employee_notification_count": len(final["notifications"]["employee"]),
            "synthetic_request_count": 1, "employee_review_http_status": 403, "api_call_count": api.calls,
        }
        state["summary"] = summary
        save_checkpoint(path, state)
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--credentials", default=".local/live-credentials.json")
    parser.add_argument("--checkpoint", default=".local/live-workflow.json")
    parser.add_argument("--start-date", help="Synthetic leave date YYYY-MM-DD; defaults to 30 days from the user's current date")
    parser.add_argument("--preflight-only", action="store_true", help="Log in and verify demo profiles; do not create or approve a request")
    args = parser.parse_args()
    try:
        accounts = credentials(ignored_path(args.credentials))
        checkpoint = ignored_path(args.checkpoint)
        api = API(args.base_url)
        actors = preflight(api, accounts)
        result = ({"status": "ready", **actors, "verified_at": now(), "api_call_count": api.calls}
                  if args.preflight_only else workflow(api, checkpoint, actors, args.start_date))
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except VerificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "verified_at": now()}), file=sys.stderr)
        return 1
    except Exception:
        # No traceback: unexpected library errors can include sensitive context.
        print(json.dumps({"status": "failed", "error": "Unexpected local verification failure; preserve the checkpoint", "verified_at": now()}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
