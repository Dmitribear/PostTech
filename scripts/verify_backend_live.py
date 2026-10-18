"""Exercise real Auth/API/database flows using marked synthetic accounts only."""

from datetime import date, timedelta
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_live_workflow import API, VerificationError, now, read_json, require
from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client


def run():
    accounts = read_json(ROOT / ".local/scenario-credentials.json")
    require(accounts["project_ref"] == "zcsoipcwymhowmvnytxf", "Unexpected fixture project")
    require(str(get_settings().supabase_url).rstrip("/") == "https://zcsoipcwymhowmvnytxf.supabase.co", "Unexpected cleanup database")
    api = API("http://127.0.0.1:8000")
    marker = "[SYNTHETIC BACKEND CHECK] " + uuid4().hex
    report_path = ROOT / ".local/backend-live-check.json"
    report = {"checked_at": now(), "backend": "Docker API + Supabase Auth/PostgreSQL", "checks": [], "request_ids": [], "marker": marker}
    profiles = {}

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def passed(name):
        report["checks"].append(name)
        save()
        print(name, flush=True)

    def balance():
        return api.call("GET", "/workspace/leave-balance", "employee")

    def snapshot(request_id):
        return {
            "history": api.call("GET", f"/requests/{request_id}/history", "employee"),
            "notifications": {role: api.rows("/notifications", role, request_id=request_id) for role in ("employee", "manager")},
        }

    api.call("GET", "/profile", expected=401)
    for actor in ("employee", "manager", "director", "hr", "outsider"):
        account = accounts[actor]
        require(account["email"] == f"scenario.{actor}+{accounts['fixture_id']}@posttech.demo", "Not a synthetic account")
        auth = api.call("POST", "/auth/login", body={k: account[k] for k in ("email", "password")})
        api.tokens[actor] = auth["access_token"]
        profile = api.call("GET", "/profile", actor)
        require(profile["id"] == account["profile_id"] and profile["external_source"] == "posttech-scenario-check", "Fixture identity mismatch")
        profiles[actor] = profile
    passed("real_auth_five_accounts_and_anonymous_denied")
    api.call("GET", "/admin/employees", "employee", expected=403)
    api.call("GET", "/admin/employees", "manager", expected=403)
    passed("employee_and_manager_cannot_use_hr_administration")
    route = api.call("GET", "/requests/routing", "employee")
    require([p["id"] for p in route["approvers"]] == [profiles["manager"]["id"]], "Unexpected employee route")
    manager_route = api.call("GET", "/requests/routing", "manager")
    require(all(p["id"] != profiles["manager"]["id"] for p in manager_route["approvers"]), "Manager self-approval route")
    passed("employee_and_manager_own_request_routes")
    initial = balance()
    require(initial["available_days"] >= 1, "Synthetic fixture has no available leave")
    existing = api.rows("/requests", "employee", scope="mine")
    day = date.today() + timedelta(days=500)
    while any(r["request_type"] == "leave" and r["status"] in ("pending", "approved") and r["start_date"] <= day.isoformat() <= r["end_date"] for r in existing):
        day += timedelta(days=1)
    db = get_supabase_client()
    try:
        for decision in ("cancelled", "rejected", "approved"):
            payload = {"request_type": "leave", "start_date": day.isoformat(), "end_date": day.isoformat(), "comment": marker}
            key = str(uuid4())
            row = api.call("POST", "/requests", "employee", payload, expected=201, key=key)
            request_id = row["id"]
            report["request_ids"].append(request_id)
            save()
            require(row["status"] == "pending", "New request is not pending")
            before = snapshot(request_id)
            require(api.call("POST", "/requests", "employee", payload, expected=201, key=key)["id"] == request_id and snapshot(request_id) == before, "Create retry duplicated effects")
            held = balance()
            require(held["available_days"] == initial["available_days"] - 1 and held["official_days"] == initial["official_days"], "Leave reservation is incorrect")
            require(any(r["id"] == request_id for r in api.rows("/requests", "manager", scope="review", status="pending")), "New request absent from reviewer queue")
            require(any(n["notification_type"] == "request_created" for n in before["notifications"]["manager"]), "Reviewer notification missing")
            api.call("GET", f"/requests/{request_id}", "outsider", expected=403)
            api.call("PATCH", f"/requests/{request_id}/review", "employee", {"status": "approved"}, expected=403)
            passed(decision + "_creation_reservation_notifications_permissions_idempotency")
            if decision == "cancelled":
                result = api.call("POST", f"/requests/{request_id}/cancel", "employee")
            else:
                if decision == "rejected":
                    api.call("PATCH", f"/requests/{request_id}/review", "manager", {"status": "rejected", "reviewer_comment": ""}, expected=422)
                result = api.call("PATCH", f"/requests/{request_id}/review", "manager", {"status": decision, "reviewer_comment": marker})
            require(result["status"] == decision, "Decision not applied")
            after = snapshot(request_id)
            require([e["event_type"] for e in after["history"]] == ["created", decision], "History is not atomic")
            require(api.call("GET", f"/requests/{request_id}", "employee")["status"] == decision, "Employee cannot see final status")
            require(not any(r["id"] == request_id for r in api.rows("/requests", "manager", scope="review", status="pending")), "Terminal request remains in reviewer queue")
            note_type = "request_cancelled" if decision == "cancelled" else "request_status_changed"
            require(sum(n["notification_type"] == note_type for n in after["notifications"]["employee"]) == 1, "Employee notification missing or duplicated")
            if decision == "cancelled":
                api.call("POST", f"/requests/{request_id}/cancel", "employee")
            else:
                api.call("PATCH", f"/requests/{request_id}/review", "manager", {"status": decision, "reviewer_comment": marker})
                api.call("POST", f"/requests/{request_id}/cancel", "employee", expected=409)
            require(snapshot(request_id) == after, "Decision retry duplicated events")
            opposite = "rejected" if decision == "approved" else "approved"
            api.call("PATCH", f"/requests/{request_id}/review", "manager", {"status": opposite, "reviewer_comment": marker}, expected=409)
            current = balance()
            require(current["official_days"] == initial["official_days"], "Official leave balance changed")
            require(current["available_days"] == initial["available_days"] - (1 if decision == "approved" else 0), "Reservation was released or retained incorrectly")
            passed(decision + "_status_history_notifications_balance_and_repeat_protection")

        courses = api.call("GET", "/academy/my-courses", "employee")
        require(bool(courses), "Synthetic fixture has no assigned courses")
        def no_answers(value):
            if isinstance(value, dict):
                require(not {"answer_index", "answers"}.intersection(value), "Quiz solutions exposed")
                for child in value.values(): no_answers(child)
            elif isinstance(value, list):
                for child in value: no_answers(child)
        no_answers(courses)
        course_id = courses[0].get("course_id") or courses[0]["id"]
        no_answers(api.call("GET", f"/academy/courses/{course_id}", "employee"))
        no_answers(api.call("GET", f"/academy/courses/{course_id}/attempts", "employee"))
        passed("assigned_courses_material_and_attempts_without_quiz_solutions")
        report["status"] = "passed"
    except Exception:
        report["status"] = "failed"
        raise
    finally:
        rows = db.table("hr_requests").select("id,employee_id,comment").eq("comment", marker).execute().data or []
        for row in rows:
            require(row["employee_id"] == profiles["employee"]["id"] and row["comment"] == marker, "Cleanup scope mismatch")
            db.table("integration_outbox").delete().eq("aggregate_id", row["id"]).execute()
            db.table("fulfillment_events").delete().eq("request_id", row["id"]).execute()
            db.table("hr_requests").delete().eq("id", row["id"]).eq("employee_id", row["employee_id"]).eq("comment", marker).execute()
        require(not db.table("hr_requests").select("id").eq("comment", marker).execute().data, "Synthetic requests remain")
        restored = balance()
        require(restored["available_days"] == initial["available_days"] and restored["official_days"] == initial["official_days"], "Fixture balance not restored")
        report["cleanup"] = "Synthetic requests and their reservations removed; balances restored"
        report["api_calls"] = api.calls
        save()
    return report


if __name__ == "__main__":
    try:
        result = run()
        print(json.dumps({"status": result["status"], "checks": len(result["checks"]), "api_calls": result["api_calls"], "cleanup": result["cleanup"]}))
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "message": str(error) if isinstance(error, VerificationError) else "See the local report; no secret diagnostics emitted"}))
        raise SystemExit(1)
