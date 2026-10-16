"""Read-only acceptance check through the local portal and real Supabase Auth.

python -m scripts.evaluate_jana_http --credentials-file .venv/jana-test-login.json
Credentials may be {email, password}, or {accounts: {worker: {email, password}}}.
Only loopback API targets are allowed; credentials/tokens are never saved in reports.
"""
import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.services.jana_local import FAQCatalog
from scripts.evaluate_jana_local import ROOT, assess_answer, summarize, validate_cases


def local_api_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/api/v1"):
        raise argparse.ArgumentTypeError("Use a loopback URL such as http://127.0.0.1:5173/api/v1")
    return value.rstrip("/")


def catalog_source_issues(catalog: FAQCatalog, articles: list[dict]) -> list[str]:
    """Check every card even when all its evaluation questions get refused."""
    issues = []
    for card in catalog.cards:
        matches = [a for a in articles if str(a["id"]) == str(card.article_id) and a.get("active") is not False]
        if (len(matches) != 1 or card.excerpt not in matches[0].get("content", "")
                or hashlib.sha256(matches[0]["content"].encode("utf-8")).hexdigest() != card.source_sha256):
            issues.append(card.id)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=local_api_url, default="http://127.0.0.1:5173/api/v1")
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--account", default="worker")
    parser.add_argument("--cases", type=Path, default=ROOT / "knowledge_base/demo/acceptance_v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".venv/jana-acceptance-http.json")
    args = parser.parse_args()
    suite = json.loads(args.cases.read_text(encoding="utf-8"))
    catalog_path = ROOT / "knowledge_base/faq.json"
    catalog = FAQCatalog.model_validate_json(catalog_path.read_text(encoding="utf-8"))
    validate_cases(suite["cases"], catalog)
    credentials = json.loads(args.credentials_file.read_text(encoding="utf-8"))
    account = credentials["accounts"][args.account] if "accounts" in credentials else credentials
    if not all(isinstance(account.get(key), str) and account[key] for key in ("email", "password")):
        parser.error("Credentials file must contain email and password")
    report = {"execution": "authenticated_local_http", "base_url": args.base_url,
              "created_at": datetime.now(UTC).isoformat(), "suite_name": suite.get("name"),
              "suite_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
              "expected_faq_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
              "notice": "Real local API and published Supabase sources. Server model settings are not introspected. Only Auth sign-in and read-only HR/AI calls. No credentials in report.",
              "results": [], "completed": False}
    try:
        with httpx.Client(base_url=args.base_url, timeout=60, follow_redirects=False) as api:
            anonymous_question = api.post("/ai/ask", json={"question": "Как оформить отпуск?"})
            first_id = str(catalog.cards[0].article_id)
            anonymous_source = api.get(f"/ai/sources/{first_id}")
            report["anonymous_access_denied"] = anonymous_question.status_code == anonymous_source.status_code == 401
            login = api.post("/auth/login", json={key: account[key] for key in ("email", "password")})
            login.raise_for_status()
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            profile = api.get("/profile", headers=headers)
            profile.raise_for_status()
            report["role"] = profile.json()["role"]
            articles = []
            for article_id in sorted({str(card.article_id) for card in catalog.cards}):
                response = api.get(f"/ai/sources/{article_id}", headers=headers)
                response.raise_for_status()
                articles.append(response.json())
            report["source_content_sha256"] = {
                a["id"]: hashlib.sha256(a["content"].encode("utf-8")).hexdigest() for a in articles}
            report["catalog_source_issues"] = catalog_source_issues(catalog, articles)
            if report["catalog_source_issues"]:
                print("Published sources disagree with FAQ cards: " + ", ".join(report["catalog_source_issues"]), flush=True)
            for position, case in enumerate(suite["cases"], 1):
                started = time.perf_counter()
                response = api.post("/ai/ask", headers=headers, json={"question": case["question"]})
                response.raise_for_status()
                result = response.json()
                outcome = assess_answer(case, result, catalog, articles)
                report["results"].append({"id": case.get("id", f"case-{position:03d}"),
                    "category": case.get("category", "uncategorized"), "question": case["question"],
                    "expected_card": case.get("card"), "expected": case.get("expected"),
                    "outcome": outcome, "checks_passed": outcome == "pass", "result": result,
                    "seconds": round(time.perf_counter() - started, 4)})
                print(f"{position}/{len(suite['cases'])}: {case.get('id', position)} {outcome}", flush=True)
            report["completed"] = True
    except httpx.HTTPError as exc:
        # Never include a response body or request headers in diagnostics.
        response = getattr(exc, "response", None)
        report["error"] = {"type": type(exc).__name__, "status": response.status_code if response is not None else None}
        print("HTTP check interrupted; safe error metadata saved.")
    report["passed"] = sum(row["checks_passed"] for row in report["results"])
    report["total"] = len(report["results"])
    report["planned_total"] = len(suite["cases"])
    report["summary"] = summarize(report["results"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {args.output.resolve()}")
    print(f"Passed: {report['passed']}/{report['total']}; planned: {report['planned_total']}")
    if not report["completed"]:
        return 2
    return 0 if (report["passed"] == report["total"] and report["anonymous_access_denied"]
                 and not report["catalog_source_issues"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
