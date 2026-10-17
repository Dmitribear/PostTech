"""Preserve a first run against fact-labelled cases without card-ID grading.

Source integrity is automatic; semantic completeness is reviewed separately
against the facts frozen before inference. No application settings are changed.
"""

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.infrastructure.config import get_settings
from app.application.dto.jana import JanaAnswer
from app.infrastructure.ai.jana_local import FAQCatalog, answer_from_faq, get_index
from scripts.evaluate_jana_http import catalog_source_issues, local_api_url
from scripts.evaluate_jana_local import ROOT, assess_answer

BEHAVIORS = {
    "supported",
    "unknown_fact",
    "clarification",
    "action_request",
    "personal_data",
    "injection",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_cases(suite: dict) -> list[dict]:
    cases = suite["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("Expected non-empty cases")
    ids, questions = set(), set()
    for case in cases:
        question = case["question"]
        normalized = " ".join(question.split()).casefold()
        if (
            case["id"] in ids
            or normalized in questions
            or not 3 <= len(question) <= 2000
        ):
            raise ValueError("Invalid or duplicate case")
        if case["expected_behavior"] not in BEHAVIORS:
            raise ValueError("Unknown expected behavior")
        if not case["required_facts"] or not all(
            isinstance(f, str) and f.strip() for f in case["required_facts"]
        ):
            raise ValueError("Every case needs predeclared minimum content")
        ids.add(case["id"])
        questions.add(normalized)
    return cases


def inspect_response(
    result: dict, catalog, articles: list[dict]
) -> tuple[str, str | None]:
    """Validate authentic evidence, deliberately without deciding relevance."""
    try:
        JanaAnswer.model_validate(result)
    except ValueError:
        return "invalid_response", None
    if result.get("mode") == "refusal":
        return assess_answer({"expected": "refusal"}, result, catalog, articles), None
    sources = result.get("sources", [])
    if len(sources) != 1:
        return "invalid_evidence", None
    matches = [
        c
        for c in catalog.cards
        if str(c.article_id) == sources[0].get("id")
        and c.excerpt == sources[0].get("excerpt")
    ]
    if len(matches) != 1:
        return "invalid_evidence", None
    card = matches[0]
    # The actual card is used ONLY to reuse quote/hash/contract validation.
    # This does not award semantic credit for choosing that card.
    return assess_answer({"card": card.id}, result, catalog, articles), card.id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "http"), required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--runtime-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--account", default="worker")
    parser.add_argument(
        "--base-url", type=local_api_url, default="http://127.0.0.1:5173/api/v1"
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; first runs must not be overwritten")
    suite = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = validate_cases(suite)
    freeze = json.loads(args.runtime_freeze.read_text(encoding="utf-8"))
    expected = {ROOT / name: value for name, value in freeze["sha256"].items()}
    expected[args.cases.resolve()] = digest(args.cases)
    if any(digest(path) != value for path, value in expected.items()):
        parser.error("Frozen runtime/input changed before inference")
    settings = get_settings()
    catalog = FAQCatalog.model_validate_json(
        settings.jana_faq_path.read_text(encoding="utf-8")
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "execution": args.mode,
        "suite_sha256": digest(args.cases),
        "runtime_freeze_sha256": digest(args.runtime_freeze),
        "runner_sha256": digest(Path(__file__)),
        "faq_sha256": digest(settings.jana_faq_path),
        "min_score": settings.jana_min_score,
        "margin": settings.jana_score_margin,
        "planned_total": len(cases),
        "completed": False,
        "results": [],
        "notice": "No card-ID gold scoring. Authenticity checks do not establish relevance or completeness. See separate content review.",
    }
    api = None
    try:
        if args.mode == "local":
            articles = json.loads(
                (ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8")
            )["articles"]
            started = time.perf_counter()
            index = get_index(settings)
            report["model_load_seconds"] = round(time.perf_counter() - started, 4)
        else:
            if not args.credentials_file:
                parser.error("HTTP mode requires a local credentials file")
            credentials = json.loads(args.credentials_file.read_text(encoding="utf-8"))
            account = (
                credentials["accounts"][args.account]
                if "accounts" in credentials
                else credentials
            )
            api = httpx.Client(
                base_url=args.base_url, timeout=60, follow_redirects=False
            )
            anonymous = api.post("/ai/ask", json={"question": "Как оформить отпуск?"})
            anonymous_source = api.get(f"/ai/sources/{catalog.cards[0].article_id}")
            report["anonymous_access_denied"] = (
                anonymous.status_code == anonymous_source.status_code == 401
            )
            login = api.post(
                "/auth/login", json={k: account[k] for k in ("email", "password")}
            )
            login.raise_for_status()
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            profile = api.get("/profile", headers=headers)
            profile.raise_for_status()
            report["role"] = profile.json()["role"]
            articles = []
            for article_id in sorted({str(c.article_id) for c in catalog.cards}):
                response = api.get(f"/ai/sources/{article_id}", headers=headers)
                response.raise_for_status()
                articles.append(response.json())
        report["source_content_sha256"] = {
            a["id"]: hashlib.sha256(a["content"].encode("utf-8")).hexdigest()
            for a in articles
        }
        report["catalog_source_issues"] = catalog_source_issues(catalog, articles)
        if report["catalog_source_issues"]:
            raise ValueError("Source preflight failed")
        for case in cases:
            started = time.perf_counter()
            if args.mode == "local":
                result = answer_from_faq(
                    case["question"],
                    articles,
                    index,
                    settings.jana_min_score,
                    settings.jana_score_margin,
                )
            else:
                response = api.post(
                    "/ai/ask", headers=headers, json={"question": case["question"]}
                )
                response.raise_for_status()
                result = response.json()
            integrity, card_id = inspect_response(result, catalog, articles)
            observation = (
                "invalid_response_or_evidence"
                if integrity != "pass"
                else "false_refusal"
                if case["expected_behavior"] == "supported"
                and result["mode"] == "refusal"
                else "content_review_required"
            )
            report["results"].append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "expected_behavior": case["expected_behavior"],
                    "result": result,
                    "actual_card": card_id,
                    "integrity": integrity,
                    "automatic_observation": observation,
                    "seconds": round(time.perf_counter() - started, 4),
                }
            )
        report["completed"] = True
    except Exception as exc:
        response = getattr(exc, "response", None)
        report["error"] = {
            "type": type(exc).__name__,
            "status": response.status_code if response is not None else None,
        }
    finally:
        if api is not None:
            api.close()
    report["changed_inputs"] = [
        str(p.relative_to(ROOT)) for p, value in expected.items() if digest(p) != value
    ]
    report["total"] = len(report["results"])
    report["automatic_observations"] = dict(
        Counter(r["automatic_observation"] for r in report["results"])
    )
    report["integrity_counts"] = dict(
        Counter(r["integrity"] for r in report["results"])
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as target:
        target.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "completed",
                    "total",
                    "automatic_observations",
                    "integrity_counts",
                    "changed_inputs",
                )
            },
            ensure_ascii=False,
        )
    )
    return (
        0
        if report["completed"]
        and not report["changed_inputs"]
        and not report["catalog_source_issues"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
