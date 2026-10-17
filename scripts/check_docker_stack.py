"""Exercise only the generated local Docker demo through its public website.

Creates clearly marked local test requests. Never reads .env or accepts a remote URL.
Run after start_docker.ps1; --scope core skips model inference.
"""
import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from icalendar import Calendar

ROOT = Path(__file__).resolve().parents[1]
EMAILS = {"worker": "employee@posttech.demo", "manager": "manager@posttech.demo",
          "director": "director@posttech.demo", "hr_admin": "hr@posttech.demo"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("core", "calendar", "jana", "all"), default="all")
    args = parser.parse_args()
    config = dotenv_values(ROOT / ".local/docker.env")
    if config.get("COMPOSE_PROJECT_NAME") != "posttech-local":
        raise SystemExit("Generate the dedicated local Docker config first")
    port = int(config["POSTTECH_HTTP_PORT"])
    if not 1 <= port <= 65535:
        raise SystemExit("Invalid local port")
    password = config["POSTTECH_DEMO_PASSWORD"]
    if not password:
        raise SystemExit("Local demo password is missing")
    base = f"http://127.0.0.1:{port}"
    report = {"scope": args.scope, "base_url": base, "shared_supabase_used": False,
              "transport": "Real nginx, FastAPI, GoTrue, PostgREST and PostgreSQL containers",
              "checks": [], "run_id": str(uuid4())}
    headers, profiles = {}, {}

    def check(name, condition, **facts):
        report["checks"].append({"name": name, "passed": bool(condition), **facts})
        print(name + (": passed" if condition else ": FAILED"), flush=True)
        if not condition:
            raise AssertionError(name)

    with httpx.Client(base_url=base, timeout=330, trust_env=False, follow_redirects=False) as client:
        def request(role, method, path, expected=200, **kwargs):
            assert path.startswith("/api/v1/") and not urlsplit(path).netloc
            response = client.request(method, path, headers=headers.get(role, {}), **kwargs)
            check(f"{role or 'anonymous'} {method} {path}", response.status_code == expected,
                  status=response.status_code)
            return response

        try:
            page = client.get("/")
            check("Built portal served", page.status_code == 200 and "/assets/" in page.text)
            request(None, "GET", "/api/v1/health/ready")
            request(None, "GET", "/api/v1/profile", expected=401)
            for role, email in EMAILS.items():
                login = request(None, "POST", "/api/v1/auth/login", json={"email": email, "password": password}).json()
                headers[role] = {"Authorization": "Bearer " + login["access_token"]}
                profiles[role] = request(role, "GET", "/api/v1/profile").json()
                check("Verified role " + role, profiles[role]["role"] == role)

            if args.scope in {"core", "all"}:
                before = request("worker", "GET", "/api/v1/workspace/leave-balance").json()
                existing = request("worker", "GET", "/api/v1/requests?scope=mine&limit=100").json()
                start = date.today() + timedelta(days=45)
                while any(r["request_type"] == "leave" and r["status"] in {"pending", "pending_hr", "approved"}
                          and date.fromisoformat(r["start_date"]) <= start + timedelta(days=1)
                          and date.fromisoformat(r["end_date"]) >= start for r in existing):
                    start += timedelta(days=7)
                end = start + timedelta(days=1)
                payload = {"request_type": "leave", "start_date": start.isoformat(), "end_date": end.isoformat(),
                           "comment": "LOCAL DOCKER SMOKE " + report["run_id"]}
                created = request("worker", "POST", "/api/v1/requests", expected=201, json=payload).json()
                rid = created["id"]
                report["leave_request_id"] = rid
                check("Leave starts pending", created["status"] == "pending")
                request("director", "GET", f"/api/v1/requests/{rid}", expected=403)
                review = {"status": "approved", "reviewer_comment": "LOCAL DOCKER SMOKE"}
                request("worker", "PATCH", f"/api/v1/requests/{rid}/review", expected=403, json=review)
                request("hr_admin", "PATCH", f"/api/v1/requests/{rid}/review", expected=409, json=review)
                unchanged = request("worker", "GET", f"/api/v1/requests/{rid}").json()
                check("Premature HR review leaves request pending", unchanged["status"] == "pending")
                first = request("manager", "PATCH", f"/api/v1/requests/{rid}/review", json=review).json()
                check("Manager forwards to HR", first["status"] == "pending_hr")
                request("worker", "GET", f"/api/v1/requests/{rid}/calendar.ics", expected=409)
                final = request("hr_admin", "PATCH", f"/api/v1/requests/{rid}/review", json=review).json()
                check("HR makes final decision", final["status"] == "approved")
                request("hr_admin", "PATCH", f"/api/v1/requests/{rid}/review", json=review)
                after = request("worker", "GET", "/api/v1/workspace/leave-balance").json()
                check("Exactly one two-day debit", before["official_days"] - after["official_days"] == 2,
                      official_before=before["official_days"], official_after=after["official_days"])
                check("Final approval closes the hold", after["pending_days"] == before["pending_days"])
                ics = request("worker", "GET", f"/api/v1/requests/{rid}/calendar.ics")
                event = Calendar.from_ical(ics.content).walk("VEVENT")[0]
                check("Calendar includes both boundary dates", event.decoded("DTSTART") == start
                      and event.decoded("DTEND") == end + timedelta(days=1), start=start.isoformat(), end=end.isoformat())
                check("Calendar response is a download", "attachment" in ics.headers.get("content-disposition", ""))
                fulfillment = request("hr_admin", "GET", f"/api/v1/workspace/fulfillment/{rid}").json()
                check("Approval creates HR document queue", fulfillment["status"] == "awaiting_hr")
                request("hr_admin", "POST", f"/api/v1/workspace/fulfillment/{rid}", expected=409, json={"action": "start"})
                completed = request("hr_admin", "POST", f"/api/v1/workspace/fulfillment/{rid}",
                    json={"action": "complete", "reference": "LOCAL-" + report["run_id"][:8], "note": "Fictional local smoke document"}).json()
                check("Manual local document completed", completed["status"] == "completed")
                after_document = request("worker", "GET", "/api/v1/workspace/leave-balance").json()
                check("Document does not debit twice", after_document["official_days"] == after["official_days"])
                manager_request = request("manager", "POST", "/api/v1/requests", expected=201,
                    json={"request_type": "advance", "amount": 100, "comment": "LOCAL DOCKER DIRECTOR " + report["run_id"]}).json()
                mid = manager_request["id"]
                report["director_review_request_id"] = mid
                result = request("director", "PATCH", f"/api/v1/requests/{mid}/review", json=review).json()
                check("Director reviews direct report", result["status"] == "pending_hr")
                request("hr_admin", "PATCH", f"/api/v1/requests/{mid}/review", json=review)
                for role in EMAILS:
                    summary = request(role, "GET", "/api/v1/workspace/summary").json()
                    check("Scoped summary " + role, isinstance(summary.get("sections"), list) and bool(summary.get("as_of")))
                request("worker", "GET", "/api/v1/workspace/employee-import/template", expected=403)
                request("hr_admin", "GET", "/api/v1/workspace/employee-import/template")
                request("hr_admin", "GET", "/api/v1/workspace/tracks")
                request("worker", "GET", "/api/v1/workspace/my-tracks")
                request("worker", "GET", "/api/v1/academy/courses")
                request("hr_admin", "POST", "/api/v1/workspace/workflow-policy/run")
                policy = request("hr_admin", "GET", "/api/v1/workspace/workflow-policy").json()
                check("Reminder worker cycle recorded", bool(policy.get("last_run_at")))

            if args.scope in {"calendar", "all"}:
                request(None, "GET", "/api/v1/requests/calendar.ics", expected=401)
                request("worker", "GET", "/api/v1/requests/calendar.ics?scope=team", expected=403)
                request("worker", "GET", "/api/v1/requests/calendar.ics?start_date=2026-12-31&end_date=2026-01-01", expected=422)
                for role in EMAILS:
                    allowed, offset = [], 0
                    while True:
                        page = request(role, "GET", f"/api/v1/requests?scope=all&request_type=leave&status=approved&limit=100&offset={offset}").json()
                        allowed.extend(page)
                        if len(page) < 100:
                            break
                        offset += len(page)
                    for scope in (["mine", "all"] if role == "worker" else ["mine", "team", "all"]):
                        expected = [row for row in allowed if scope == "all" or
                                    (row["employee_id"] == profiles[role]["id"]) == (scope == "mine")]
                        response = request(role, "GET", f"/api/v1/requests/calendar.ics?scope={scope}")
                        exported = Calendar.from_ical(response.content).walk("VEVENT")
                        by_id = {str(event["uid"])[6:].removesuffix("@posttech.local"): event for event in exported}
                        check(f"Project calendar scope {role}/{scope}", set(by_id) == {row["id"] for row in expected}, event_count=len(exported))
                        check(f"Project calendar count {role}/{scope}", response.headers.get("x-calendar-event-count") == str(len(expected)))
                        for row in expected:
                            event = by_id[row["id"]]
                            check(f"Project dates {role}/{scope}/{row['id']}",
                                  event.decoded("dtstart") == date.fromisoformat(row["start_date"]) and
                                  event.decoded("dtend") == date.fromisoformat(row["end_date"]) + timedelta(days=1))

            if args.scope in {"jana", "all"}:
                question = "Кто окончательно одобряет отпуск?"
                started = time.monotonic()
                answer = request("worker", "POST", "/api/v1/ai/ask", json={"question": question}).json()
                report["jana"] = {"question": question, "seconds": round(time.monotonic()-started, 2), "answer": answer}
                check("Jana returns evidence about HR", answer["grounded"] and answer["sources"] and "HR" in answer["answer"])
                for source in answer["sources"]:
                    document = request("worker", "GET", source["url"]).json()
                    check("Exact and current source", source["excerpt"] in document["content"] and source["version"] == document["version"])
                unknown = request("worker", "POST", "/api/v1/ai/ask", json={"question": "Какой пароль у Wi-Fi в офисе JanaPost?"}).json()
                report["unknown_answer"] = unknown
                check("Unknown fact is not invented", not unknown["grounded"] and not unknown["sources"])
            report["result"] = "passed"
        except Exception as exc:
            report["result"] = "failed"
            report["error"] = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            target = ROOT / f"docs/reports/team-integration/docker-http-{args.scope}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Report: {target.name}", flush=True)


if __name__ == "__main__":
    main()
