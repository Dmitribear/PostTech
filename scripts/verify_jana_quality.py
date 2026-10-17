"""Run the versioned 30-question corpus through the real API. No personal queries."""

from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]


def run(
    base_url: str, credentials: Path, report: Path, require_generation: bool = False
) -> dict:
    state = json.loads(credentials.read_text(encoding="utf-8-sig"))
    cases = json.loads((ROOT / "evals/jana_questions.json").read_text(encoding="utf-8"))
    results = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=50) as client:
        account = state["employee"]
        login = client.post(
            "/api/v1/auth/login",
            json={"email": account["email"], "password": account["password"]},
        )
        if login.status_code != 200:
            raise RuntimeError("Test account sign-in failed")
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        for case in cases:
            response = client.post(
                "/api/v1/ai/ask", json={"question": case["question"]}
            )
            checks = {"http_ok": response.status_code == 200}
            mode, fallback_reason = None, None
            if checks["http_ok"]:
                answer = response.json()
                mode, fallback_reason = (
                    answer.get("mode"),
                    answer.get("fallback_reason"),
                )
                if require_generation and case["grounded"]:
                    checks["real_generation"] = mode == "generated"
                checks["expected_grounding"] = (
                    answer.get("grounded") is case["grounded"]
                )
                checks["expected_escalation"] = (
                    answer.get("escalation_suggested") is not case["grounded"]
                )
                sources = answer.get("sources", [])
                expected_titles = case.get(
                    "source_contains_any", [case.get("source_contains", "")]
                )
                checks["citations"] = (
                    (
                        bool(sources)
                        and any(
                            term in s["title"].lower()
                            for s in sources
                            for term in expected_titles
                        )
                    )
                    if case["grounded"]
                    else not sources
                )
                checks["freshness_metadata"] = all(
                    s.get("freshness") in {"unverified", "reviewed"} for s in sources
                )
                checks["source_readable"] = all(
                    client.get(f"/api/v1/ai/sources/{s['id']}").status_code == 200
                    for s in sources
                )
            results.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "question": case["question"],
                    "checks": checks,
                    "mode": mode,
                    "fallback_reason": fallback_reason,
                    "passed": all(checks.values()),
                }
            )
    data = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "results": results,
        "scope": "Curated corpus, not a universal accuracy estimate. No passwords, sessions or personal responses stored.",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument(
        "--credentials", type=Path, default=ROOT / ".local/scenario-credentials.json"
    )
    p.add_argument(
        "--report", type=Path, default=ROOT / ".local/jana-quality-report.json"
    )
    p.add_argument(
        "--require-generation",
        action="store_true",
        help="Fail if any expected answer is only a fallback excerpt",
    )
    args = p.parse_args()
    try:
        r = run(args.base_url, args.credentials, args.report, args.require_generation)
        print(
            json.dumps(
                {
                    "total": r["total"],
                    "passed": r["passed"],
                    "failed_ids": [v["id"] for v in r["results"] if not v["passed"]],
                }
            )
        )
        sys.exit(0 if r["total"] == r["passed"] else 1)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": "Check API readiness and private test account configuration.",
                }
            )
        )
        sys.exit(1)
