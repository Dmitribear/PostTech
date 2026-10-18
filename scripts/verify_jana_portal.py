"""Evaluate Jana's portal answers, conditions and navigation on synthetic accounts.

The default corpus is the same 49 questions as the original live audit. Automated
checks are regression signals; every answer still needs a semantic review.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Iterator

import httpx


ROOT = Path(__file__).resolve().parents[1]
ACTION_ROUTES = {
    "leave_new": "/calendar?select=1",
    "advance_new": "/requests/new?type=advance",
    "requests_mine": "/requests",
    "academy": "/academy",
    "profile": "/profile",
    "calendar": "/calendar",
    "notifications": "/notifications",
    "requests_review": "/requests?scope=review",
    "support": "/support",
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in patterns)


def evaluate_answer(case: dict, answer: dict, require_generation: bool = True) -> dict:
    supported = case["expected_response"] == "supported"
    sources = answer.get("sources", [])
    actions = answer.get("actions", [])
    answer_text = answer.get("answer", "")
    checks = {
        "answer_present": isinstance(answer_text, str) and bool(answer_text.strip()),
        "expected_grounding": answer.get("grounded") is supported,
        "expected_escalation": answer.get("escalation_suggested") is case.get("expected_escalation", not supported),
        "citations": bool(sources) if supported else not sources,
        "actions_list": isinstance(actions, list),
    }
    if require_generation and supported:
        checks["real_generation"] = answer.get("mode") == "generated"
    if not supported:
        checks["refusal_mode"] = answer.get("mode") == "refusal"
        checks["no_refusal_actions"] = actions == []
    if isinstance(actions, list):
        checks["safe_action_routes"] = all(
            isinstance(action, dict)
            and action.get("id") in ACTION_ROUTES
            and action.get("href") == ACTION_ROUTES[action["id"]]
            and isinstance(action.get("label"), str)
            and bool(action["label"].strip())
            for action in actions
        )
        action_ids = [a.get("id") for a in actions if isinstance(a, dict)]
        checks["unique_actions"] = len(action_ids) == len(set(action_ids))
        checks["required_actions"] = set(case.get("required_actions", [])) <= set(action_ids)
        if case.get("one_of_actions"):
            checks["one_of_actions"] = bool(set(case["one_of_actions"]) & set(action_ids))
        if case.get("expected_action_labels"):
            labels = case["expected_action_labels"]
            checks["localized_action_labels"] = all(
                action.get("label") == labels.get(action.get("id")) for action in actions
            )
        checks["worker_has_no_review_action"] = "requests_review" not in action_ids
    if isinstance(answer_text, str):
        for condition in case.get("conditions", []):
            applies = not condition.get("when_any") or matches(answer_text, condition["when_any"])
            checks["condition:" + condition["id"]] = not applies or (
                matches(answer_text, condition["any_patterns"])
                and not matches(answer_text, condition.get("none_patterns", []))
            )
        for forbidden in case.get("forbidden_claims", []):
            checks["forbidden:" + forbidden["id"]] = not matches(answer_text, forbidden["any_patterns"])
    else:
        checks["valid_answer_type"] = False
    return checks


@contextmanager
def transport(mode: str, base_url: str) -> Iterator:
    if mode == "in-process":
        sys.path.insert(0, str(ROOT))
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    else:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=90) as client:
            yield client


def summary(results: list[dict]) -> dict:
    elapsed = [r["elapsed_ms"] for r in results]
    supported = [r for r in results if r["expected_response"] == "supported"]
    refusals = [r for r in results if r["expected_response"] == "refusal"]
    return {
        "total": len(results),
        "automated_passed": sum(r["automated_passed"] for r in results),
        "supported_expected": len(supported),
        "supported_received": sum(r.get("response", {}).get("grounded") is True for r in supported),
        "refusals_expected": len(refusals),
        "refusals_received": sum(r.get("response", {}).get("mode") == "refusal" for r in refusals),
        "modes": dict(Counter(r.get("response", {}).get("mode", "http_error") for r in results)),
        "latency_ms": {
            "minimum": min(elapsed) if elapsed else None,
            "median": round(statistics.median(elapsed)) if elapsed else None,
            "maximum": max(elapsed) if elapsed else None,
        },
        "failed_ids": [r["id"] for r in results if not r["automated_passed"]],
        "manual_review_required": True,
    }


def run(args: argparse.Namespace) -> dict:
    cases = read_json(args.corpus)
    if not isinstance(cases, list) or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Expected a corpus with unique case identifiers")
    if args.ids:
        requested = set(args.ids.split(","))
        cases = [case for case in cases if case["id"] in requested]
        if {case["id"] for case in cases} != requested:
            raise ValueError("One or more requested case identifiers do not exist")
    if not cases:
        raise ValueError("The corpus must not be empty")

    state = read_json(args.credentials)
    account = state["employee"]
    if not account["email"].endswith("@posttech.demo"):
        raise ValueError("Only the synthetic scenario account is supported")
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "corpus": args.corpus.name,
        "transport": args.transport,
        "generation_required": not args.allow_excerpts,
        "scope": "Generic portal questions using an isolated worker fixture; real Supabase/OpenAI when configured. Credentials, tokens and profile values are never stored. No mutations are requested.",
        "limitations": [
            "Automated patterns check selected conditions, not semantic correctness of every sentence.",
            "Refusals are checked for mode, grounding, citations and buttons; absence of private database reads is covered by separate unit tests.",
            "A safe fallback excerpt is reported distinctly from generated text.",
        ],
        "sources": {},
        "results": [],
    }

    def save():
        report["summary"] = summary(report["results"])
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with transport(args.transport, args.base_url) as client:
        login = client.post("/api/v1/auth/login", json={"email": account["email"], "password": account["password"]})
        if login.status_code != 200:
            raise RuntimeError("Synthetic sign-in failed")
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        profile_response = client.get("/api/v1/profile")
        if profile_response.status_code != 200:
            raise RuntimeError("Synthetic profile could not be verified")
        profile = profile_response.json()
        if (
            profile.get("id") != account["profile_id"]
            or profile.get("external_source") != "posttech-scenario-check"
            or profile.get("role") != "worker"
        ):
            raise RuntimeError("Unexpected account scope")
        for case in cases:
            started = time.perf_counter()
            row = {
                "id": case["id"],
                "original_id": case.get("original_id", case["id"]),
                "question": case["question"],
                "language": case.get("language", "ru"),
                "expected_response": case["expected_response"],
                "required_actions": case.get("required_actions", []),
                "manual_review": {"status": "pending", "prompts": case.get("review_prompts", [])},
            }
            try:
                response = client.post(
                    "/api/v1/ai/ask",
                    json={"question": case["question"]},
                    headers={"Accept-Language": case.get("language", "ru")},
                )
                row["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
                row["http_status"] = response.status_code
                row["checks"] = {"http_ok": response.status_code == 200}
                if response.status_code == 200:
                    answer = response.json()
                    row["response"] = answer
                    row["checks"].update(evaluate_answer(case, answer, not args.allow_excerpts))
                    source_results = []
                    for source in answer.get("sources", []):
                        cache_key = str(source["id"]) + ":" + str(source.get("version", ""))
                        if cache_key not in report["sources"]:
                            read = client.get(
                                "/api/v1/ai/sources/" + str(source["id"]),
                                params={"version": source["version"]} if source.get("version") else {},
                            )
                            report["sources"][cache_key] = {
                                "id": source["id"], "version": source.get("version"),
                                "title": source.get("title"), "http_status": read.status_code,
                                "freshness": source.get("freshness"),
                            }
                        source_results.append(report["sources"][cache_key])
                    row["checks"]["source_readable"] = all(s["http_status"] == 200 for s in source_results)
                    row["checks"]["reviewed_sources"] = all(s["freshness"] == "reviewed" for s in source_results)
            except Exception as exc:
                row["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
                row["checks"] = {"request_completed": False}
                row["error_type"] = type(exc).__name__
            row["automated_passed"] = all(row["checks"].values())
            row["failed_checks"] = [name for name, passed in row["checks"].items() if not passed]
            report["results"].append(row)
            save()
            print(json.dumps({
                "id": row["id"], "mode": row.get("response", {}).get("mode"),
                "ms": row["elapsed_ms"], "passed": row["automated_passed"],
                "failed_checks": row["failed_checks"],
            }, ensure_ascii=False), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("in-process", "http"), default="in-process")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--credentials", type=Path, default=ROOT / ".local/scenario-credentials.json")
    parser.add_argument("--corpus", type=Path, default=ROOT / "evals/jana_portal_questions.json")
    parser.add_argument("--report", type=Path, default=ROOT / ".local/jana-portal-report.json")
    parser.add_argument("--ids", help="Optional comma-separated case identifiers for a smoke check")
    parser.add_argument("--allow-excerpts", action="store_true", help="Allow grounded source excerpts while still recording their mode")
    args = parser.parse_args()
    try:
        report = run(args)
        print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
        return 0 if report["summary"]["automated_passed"] == report["summary"]["total"] else 1
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "message": "Check API readiness, corpus and private synthetic account configuration."}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
