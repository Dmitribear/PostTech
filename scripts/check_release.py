"""Read-only preflight for the running jury stand; does not print configuration."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import httpx


def check(base_url):
    checks = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30) as client:
        for path, expected in (
            ("/", 200),
            ("/calendar", 200),
            ("/api/v1/health/live", 200),
            ("/api/v1/health/ready", 200),
            ("/api/v1/profile", 401),
            ("/api/v1/requests/calendar.ics", 401),
            ("/assets/not-a-real-file.js", 404),
        ):
            try:
                response = client.get(path)
                passed = response.status_code == expected
                if path in ("/", "/calendar"):
                    passed = passed and bool(
                        re.search(r'/assets/[^"\s]+\.js', response.text)
                    )
                if path == "/api/v1/health/ready" and passed:
                    passed = response.json().get("status") == "ready"
                checks.append(
                    {"path": path, "status": response.status_code, "passed": passed}
                )
            except (httpx.HTTPError, ValueError):
                checks.append({"path": path, "passed": False})
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(row["passed"] for row in checks),
        "checks": checks,
        "scope": "Read-only HTTP preflight; does not prove login, role workflows or AI generation.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--report", type=Path, default=Path(".local/release-preflight.json")
    )
    args = parser.parse_args()
    result = check(args.base_url)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
