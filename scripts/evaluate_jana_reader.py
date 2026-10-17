"""Record a local-reader experiment without FAQ/card-ID scoring.

Semantic correctness is reviewed separately against predeclared facts. This
runner checks source authenticity, preserves every completed response in an
append-only journal, and never rewrites a previous experiment's output.
"""

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx

from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client
from app.application.dto.jana import JanaAnswer
from app.domain.knowledge.jana_errors import JanaUnavailable
from app.domain.knowledge.jana_evidence import MAX_ARTICLES, prepare_evidence
from app.domain.knowledge.jana_intent import BOUNDARY_MESSAGES, CLARIFICATION_MESSAGES
from app.infrastructure.ai.jana_reader import (
    LocalReader,
    answer_from_knowledge,
    unavailable_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "knowledge_base/demo/articles.json"
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


def local_api_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/api/v1"
    ):
        raise argparse.ArgumentTypeError("Use a loopback API URL ending in /api/v1")
    return value.rstrip("/")


def validate_cases(suite: dict) -> list[dict]:
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Expected a non-empty case list")
    ids, questions = set(), set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("A case must be an object")
        case_id, question = case.get("id"), case.get("question")
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or not isinstance(question, str)
        ):
            raise ValueError("A case needs a string ID and question")
        normalized = " ".join(question.split()).casefold()
        if (
            case_id in ids
            or normalized in questions
            or not 3 <= len(question.strip()) <= 2000
        ):
            raise ValueError("Invalid or duplicate case")
        if case.get("expected_behavior") not in BEHAVIORS:
            raise ValueError("Unknown expected behavior")
        facts = case.get("required_facts")
        if (
            not isinstance(facts, list)
            or not facts
            or not all(isinstance(f, str) and f.strip() for f in facts)
        ):
            raise ValueError("Every case needs predeclared minimum content")
        ids.add(case_id)
        questions.add(normalized)
    return cases


def inspect_response(result: dict, articles: list[dict]) -> str:
    """Check authenticity, not relevance, completeness or expected behavior."""
    try:
        parsed = JanaAnswer.model_validate(result)
        bundle = prepare_evidence(articles)
    except (ValueError, TypeError, JanaUnavailable):
        return "invalid_response"
    if not isinstance(result, dict) or set(result) != {
        "answer",
        "sources",
        "grounded",
        "escalation_suggested",
        "mode",
    }:
        return "invalid_response"
    if (
        type(result["grounded"]) is not bool
        or type(result["escalation_suggested"]) is not bool
    ):
        return "invalid_response"
    if parsed.mode not in {"excerpts", "refusal"}:
        return "invalid_response"
    if parsed.mode == "refusal":
        if parsed.sources or parsed.grounded:
            return "invalid_refusal"
        allowed = {
            (text, True)
            for kind, text in BOUNDARY_MESSAGES.items()
            if kind in {"unknown", "action", "personal", "injection"}
        }
        allowed.update(
            (text, False)
            for kind, text in CLARIFICATION_MESSAGES.items()
            if kind != "none"
        )
        allowed.add((unavailable_evidence()["answer"], True))
        return (
            "pass"
            if (parsed.answer, parsed.escalation_suggested) in allowed
            else "invalid_framing"
        )
    if not parsed.sources or not parsed.grounded:
        return "invalid_evidence"
    seen = set()
    for source in parsed.sources:
        article_id = str(source.id)
        article = bundle.by_article_id.get(article_id)
        if (
            article is None
            or article_id in seen
            or source.title != article.source_title
            or source.url != f"/api/v1/ai/local/sources/{article_id}"
            or not source.excerpt.strip()
            or source.excerpt not in article.content
        ):
            return "invalid_evidence"
        seen.add(article_id)
    quotes = "\n\n".join(
        f"{source.excerpt} [{number}]"
        for number, source in enumerate(parsed.sources, 1)
    )
    for kind in ("answer", "partial", "action", "personal", "injection"):
        prefix = BOUNDARY_MESSAGES[kind]
        if all(source.title.startswith("Демо:") for source in parsed.sources):
            prefix = (prefix + "\n\n" if prefix else "") + "Демонстрационные материалы:"
        expected = prefix + "\n\n" + quotes
        # An empty framing prefix may be trimmed for normal display. No other
        # whitespace changes or model-written assertion can pass this check.
        variants = {expected, quotes} if not prefix else {expected}
        if parsed.answer in variants and parsed.escalation_suggested is (
            kind != "answer"
        ):
            return "pass"
    return "invalid_framing"


def source_issues(expected: list[dict], actual: list[dict]) -> list[str]:
    """Compare the complete public fixture, independently of selected answers."""
    expected_bundle, actual_bundle = (
        prepare_evidence(expected),
        prepare_evidence(actual),
    )
    issues = []
    for article_id in sorted(
        set(expected_bundle.by_article_id) | set(actual_bundle.by_article_id)
    ):
        wanted, observed = (
            expected_bundle.by_article_id.get(article_id),
            actual_bundle.by_article_id.get(article_id),
        )
        if (
            wanted is None
            or observed is None
            or any(
                getattr(wanted, key) != getattr(observed, key)
                for key in ("title", "source_title", "content")
            )
        ):
            issues.append(article_id)
    return issues


def active_inventory() -> list[dict]:
    """Read the same complete published-knowledge boundary as the runtime.

    The public API has no article-list route. Checking only fixture source URLs
    would miss a new active article that changes the model's complete context.
    This read-only query uses the local backend configuration, never private HR
    tables; one extra row makes overflow explicit rather than truncating it.
    """
    response = (
        get_supabase_client()
        .table("knowledge_articles")
        .select("id,title,content,source_title")
        .eq("active", True)
        .order("id")
        .limit(MAX_ARTICLES + 1)
        .execute()
    )
    articles = response.data or []
    prepare_evidence(articles)
    return articles


def changed_inputs(expected: dict[Path, str]) -> list[str]:
    changed = []
    for path, value in expected.items():
        try:
            matches = path.is_file() and digest(path) == value
        except OSError:
            matches = False
        if not matches:
            changed.append(
                path.relative_to(ROOT).as_posix()
                if path.is_relative_to(ROOT)
                else str(path)
            )
    return sorted(changed)


def _write_json(target, value: dict) -> None:
    target.seek(0)
    target.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    target.truncate()
    target.flush()
    os.fsync(target.fileno())


def _journal(target, event: dict) -> None:
    target.write(json.dumps(event, ensure_ascii=False) + "\n")
    target.flush()
    os.fsync(target.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "http"), required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--runtime-freeze", type=Path)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--account", default="worker")
    parser.add_argument(
        "--base-url", type=local_api_url, default="http://127.0.0.1:5173/api/v1"
    )
    args = parser.parse_args()
    if not args.runtime_freeze and not args.development:
        parser.error("A runtime freeze is required unless --development is explicit")
    if args.limit is not None and (not args.development or args.limit <= 0):
        parser.error(
            "--limit must be positive and is available only with --development"
        )
    journal_path = args.output.with_suffix(args.output.suffix + ".jsonl")
    if args.output.exists() or journal_path.exists():
        parser.error(
            "Output/journal already exists; previous experiments must not be overwritten"
        )
    if args.mode == "http":
        if (
            not args.credentials_file
            or not args.credentials_file.resolve().is_relative_to(ROOT / ".venv")
        ):
            parser.error(
                "HTTP credentials must be in the ignored local .venv directory"
            )
    suite = json.loads(args.cases.read_text(encoding="utf-8"))
    all_cases = validate_cases(suite)
    cases = all_cases[: args.limit] if args.limit is not None else all_cases
    expected = {}
    if args.runtime_freeze:
        freeze = json.loads(args.runtime_freeze.read_text(encoding="utf-8"))
        for name, value in freeze["sha256"].items():
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT):
                parser.error("Runtime freeze paths must stay inside the repository")
            expected[path] = value
        expected[args.runtime_freeze.resolve()] = digest(args.runtime_freeze)
    # Even development runs must reveal edits made while inference was running.
    for path in (
        args.cases.resolve(),
        ARTICLES_PATH,
        Path(__file__).resolve(),
        ROOT / "app/infrastructure/config.py",
        ROOT / "app/infrastructure/ai/jana_reader.py",
        ROOT / "app/domain/knowledge/jana_evidence.py",
        ROOT / "app/domain/knowledge/jana_intent.py",
    ):
        expected.setdefault(path, digest(path))
    if changed_inputs(expected):
        parser.error("Frozen runtime/input changed before inference")
    demo_articles = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))["articles"]
    prepare_evidence(demo_articles)
    settings = get_settings()
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "execution": args.mode,
        "development": args.development,
        "blind_candidate": not args.development,
        "suite_sha256": digest(args.cases),
        "runner_sha256": digest(Path(__file__)),
        "runtime_freeze_sha256": digest(args.runtime_freeze)
        if args.runtime_freeze
        else None,
        "source_fixture_sha256": digest(ARTICLES_PATH),
        "reader_model": settings.jana_reader_model,
        "suite_total": len(all_cases),
        "planned_total": len(cases),
        "completed": False,
        "results": [],
        "source_issues": [],
        "changed_inputs": [],
        "notice": "Integrity is not semantic correctness. No FAQ/card grading. Separate frozen-label content review is required. A freeze alone does not prove question-author blindness.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started_run = time.perf_counter()
    api, current_case = None, None
    # Exclusive creation reserves both artifact names before inference. The
    # append-only journal retains completed rows even if the snapshot is lost.
    with (
        args.output.open("x", encoding="utf-8") as output,
        journal_path.open("x", encoding="utf-8") as journal,
    ):
        _write_json(output, report)
        _journal(journal, {"event": "started", "report": report})
        try:
            if args.mode == "local":
                articles = demo_articles
                reader = LocalReader(settings)
            else:
                credentials = json.loads(
                    args.credentials_file.read_text(encoding="utf-8")
                )
                account = (
                    credentials["accounts"][args.account]
                    if "accounts" in credentials
                    else credentials
                )
                if not all(
                    isinstance(account.get(key), str) and account[key]
                    for key in ("email", "password")
                ):
                    raise ValueError("Invalid local credentials file")
                api = httpx.Client(
                    base_url=args.base_url,
                    timeout=httpx.Timeout(300, connect=10),
                    trust_env=False,
                    follow_redirects=False,
                )
                first_id = prepare_evidence(demo_articles).documents[0].id
                anonymous = api.post(
                    "/ai/ask", json={"question": "Как оформить отпуск?"}
                )
                anonymous_source = api.get(f"/ai/sources/{first_id}")
                report["anonymous_access_denied"] = (
                    anonymous.status_code == anonymous_source.status_code == 401
                )
                if not report["anonymous_access_denied"]:
                    raise ValueError("Anonymous access check failed")
                login = api.post(
                    "/auth/login",
                    json={key: account[key] for key in ("email", "password")},
                )
                login.raise_for_status()
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                profile = api.get("/profile", headers=headers)
                profile.raise_for_status()
                report["role"] = profile.json()["role"]
                before_inventory = active_inventory()
                report["source_inventory_count"] = len(before_inventory)
                report["source_inventory_scope"] = (
                    "all active knowledge_articles; fixture must match exactly"
                )
                report["source_issues"] = source_issues(demo_articles, before_inventory)
                if report["source_issues"]:
                    raise ValueError(
                        "Complete published knowledge differs from frozen fixture"
                    )
                articles = []
                for document in prepare_evidence(demo_articles).documents:
                    response = api.get(f"/ai/sources/{document.id}", headers=headers)
                    response.raise_for_status()
                    articles.append(response.json())
                report["source_issues"] = source_issues(demo_articles, articles)
                if report["source_issues"]:
                    raise ValueError("Published source preflight failed")
            report["source_content_sha256"] = {
                doc.id: doc.sha256 for doc in prepare_evidence(articles).documents
            }
            _write_json(output, report)
            for position, case in enumerate(cases, 1):
                current_case = case["id"]
                started_case = time.perf_counter()
                if args.mode == "local":
                    result = answer_from_knowledge(case["question"], articles, reader)
                else:
                    response = api.post(
                        "/ai/ask", headers=headers, json={"question": case["question"]}
                    )
                    response.raise_for_status()
                    result = response.json()
                integrity = inspect_response(result, articles)
                observation = (
                    "invalid_response_or_evidence"
                    if integrity != "pass"
                    else "false_refusal"
                    if case["expected_behavior"] == "supported"
                    and result["mode"] == "refusal"
                    else "content_review_required"
                )
                row = {
                    "id": case["id"],
                    "question": case["question"],
                    "expected_behavior": case["expected_behavior"],
                    "result": result,
                    "integrity": integrity,
                    "automatic_observation": observation,
                    "seconds": round(time.perf_counter() - started_case, 4),
                }
                report["results"].append(row)
                report["elapsed_seconds"] = round(time.perf_counter() - started_run, 4)
                _journal(journal, {"event": "case", "row": row})
                _write_json(output, report)
                print(
                    f"{position}/{len(cases)} {case['id']}: {integrity}, {row['seconds']}s",
                    flush=True,
                )
            if args.mode == "http":
                # An unchanged quote may have gained a new qualification
                # elsewhere in its article during this run. Recheck complete
                # sources instead of accepting quote-substring checks alone.
                after_articles = []
                for document in prepare_evidence(demo_articles).documents:
                    response = api.get(f"/ai/sources/{document.id}", headers=headers)
                    response.raise_for_status()
                    after_articles.append(response.json())
                report["source_issues"] = source_issues(articles, after_articles)
                after_inventory = active_inventory()
                report["source_inventory_count_after"] = len(after_inventory)
                report["source_issues"] = sorted(
                    set(report["source_issues"])
                    | set(source_issues(before_inventory, after_inventory))
                )
                report["source_content_sha256_after"] = {
                    doc.id: doc.sha256
                    for doc in prepare_evidence(after_articles).documents
                }
            report["completed"] = True
        except Exception as exc:
            response = getattr(exc, "response", None)
            # Never serialize an exception message, HTTP headers/body, token or credentials.
            report["error"] = {
                "type": type(exc).__name__,
                "status": response.status_code if response is not None else None,
                "case_id": current_case,
            }
            _journal(journal, {"event": "error", "error": report["error"]})
        finally:
            if api is not None:
                api.close()
            report["changed_inputs"] = changed_inputs(expected)
            report["total"] = len(report["results"])
            report["integrity_counts"] = dict(
                Counter(row["integrity"] for row in report["results"])
            )
            report["automatic_observations"] = dict(
                Counter(row["automatic_observation"] for row in report["results"])
            )
            report["elapsed_seconds"] = round(time.perf_counter() - started_run, 4)
            report["finished_at"] = datetime.now(UTC).isoformat()
            _journal(
                journal,
                {
                    "event": "finished",
                    "completed": report["completed"],
                    "changed_inputs": report["changed_inputs"],
                    "total": report["total"],
                },
            )
            _write_json(output, report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "completed",
                    "total",
                    "integrity_counts",
                    "automatic_observations",
                    "changed_inputs",
                )
            },
            ensure_ascii=False,
        )
    )
    return (
        0
        if (
            report["completed"]
            and not report["changed_inputs"]
            and not report["source_issues"]
            and all(row["integrity"] == "pass" for row in report["results"])
        )
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
