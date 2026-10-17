"""Offline evaluation with the real local model; no API calls or downloads.

python -m scripts.evaluate_jana_local --output .venv/jana-local-evaluation.json
python -m scripts.evaluate_jana_local --question "Куда подать заявление на отпуск?"
"""

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.infrastructure.config import get_settings
from app.domain.knowledge.jana_errors import JanaUnavailable
from app.infrastructure.ai.jana_local import answer_from_faq, get_index
from app.infrastructure.ai.local_embeddings import MODEL_ID, REVISION
from app.application.dto.jana import JanaAnswer

ROOT = Path(__file__).resolve().parents[1]


def validate_cases(cases: list[dict], catalog) -> None:
    """Reject misspelled expectations instead of silently scoring them as passes."""
    if not isinstance(cases, list) or not cases:
        raise ValueError("Expected a non-empty cases list")
    card_ids = {card.id for card in catalog.cards}
    ids, questions = set(), set()
    for position, case in enumerate(cases, 1):
        case_id = case.get("id", f"case-{position:03d}")
        question = case.get("question")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise ValueError(f"Invalid or duplicate case ID at position {position}")
        if not isinstance(question, str) or not 3 <= len(question.strip()) <= 2000:
            raise ValueError(f"Invalid question in {case_id}")
        normalized = " ".join(question.split()).casefold()
        if normalized in questions:
            raise ValueError(f"Duplicate question in {case_id}")
        if ("card" in case) == ("expected" in case):
            raise ValueError(
                f"{case_id} must specify exactly one card or expected refusal"
            )
        if "card" in case and case["card"] not in card_ids:
            raise ValueError(f"Unknown card in {case_id}: {case['card']}")
        if "expected" in case and case["expected"] != "refusal":
            raise ValueError(f"Unsupported expected outcome in {case_id}")
        if not isinstance(case.get("category", "uncategorized"), str):
            raise ValueError(f"Invalid category in {case_id}")
        ids.add(case_id)
        questions.add(normalized)


def assess_answer(case: dict, result: dict, catalog, articles: list[dict]) -> str:
    """Check the complete quote and source identity, not just a plausible URL."""
    try:
        JanaAnswer.model_validate(result)
    except ValueError:
        return "invalid_response"
    if result["mode"] == "refusal":
        if (
            result["sources"]
            or result["grounded"]
            or not result["escalation_suggested"]
        ):
            return "invalid_refusal"
        return "false_refusal" if "card" in case else "pass"
    if (
        result["mode"] != "excerpts"
        or not result["grounded"]
        or result["escalation_suggested"]
    ):
        return "invalid_response"
    if len(result["sources"]) != 1:
        return "invalid_evidence"
    source = result["sources"][0]
    matches = [
        a
        for a in articles
        if str(a["id"]) == source["id"] and a.get("active") is not False
    ]
    matching_cards = [
        c
        for c in catalog.cards
        if str(c.article_id) == source["id"] and c.excerpt == source["excerpt"]
    ]
    if len(matches) != 1 or len(matching_cards) != 1:
        return "invalid_evidence"
    article, card = matches[0], matching_cards[0]
    prefix = (
        "Демо: "
        if catalog.demo and not card.excerpt.startswith("В демо-прототипе")
        else ""
    )
    if (
        card.excerpt not in article["content"]
        or hashlib.sha256(article["content"].encode("utf-8")).hexdigest()
        != card.source_sha256
        or source["url"] != f"/api/v1/ai/local/sources/{card.article_id}"
        or source["title"] != article["source_title"]
        or result["answer"] != f"{prefix}{card.excerpt} [1]"
    ):
        return "invalid_evidence"
    if "card" not in case:
        return "unexpected_answer"
    return "pass" if card.id == case["card"] else "wrong_card"


def summarize(results: list[dict]) -> dict:
    scored = [row for row in results if row["outcome"] != "not_scored"]
    supported = [row for row in scored if row.get("expected_card")]
    refusals = [row for row in scored if row.get("expected") == "refusal"]
    categories = {}
    for category in sorted({row["category"] for row in scored}):
        rows = [row for row in scored if row["category"] == category]
        categories[category] = {
            "passed": sum(r["outcome"] == "pass" for r in rows),
            "total": len(rows),
        }
    return {
        "outcomes": dict(Counter(row["outcome"] for row in scored)),
        "supported": {
            "passed": sum(row["outcome"] == "pass" for row in supported),
            "total": len(supported),
        },
        "refusals": {
            "passed": sum(row["outcome"] == "pass" for row in refusals),
            "total": len(refusals),
        },
        "categories": categories,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question")
    parser.add_argument(
        "--cases", type=Path, default=ROOT / "knowledge_base/demo/local_evaluation.json"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    suite = (
        None if args.question else json.loads(args.cases.read_text(encoding="utf-8"))
    )
    started = time.perf_counter()
    try:
        index = get_index(settings)
    except JanaUnavailable as exc:
        print(f"Local model unavailable: {exc}")
        return 2
    articles = json.loads(
        (ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8")
    )["articles"]
    cases = [{"question": args.question}] if args.question else suite["cases"]
    if not args.question:
        try:
            validate_cases(cases, index.catalog)
        except ValueError as exc:
            parser.error(str(exc))
    report = {
        "model": MODEL_ID,
        "revision": REVISION,
        "min_score": settings.jana_min_score,
        "margin": settings.jana_score_margin,
        "load_seconds": round(time.perf_counter() - started, 3),
        "execution": "local_cpu_demo_articles",
        "created_at": datetime.now(UTC).isoformat(),
        "faq_sha256": hashlib.sha256(settings.jana_faq_path.read_bytes()).hexdigest(),
        "articles_sha256": hashlib.sha256(
            (ROOT / "knowledge_base/demo/articles.json").read_bytes()
        ).hexdigest(),
        "suite_name": suite.get("name", args.cases.name) if suite else None,
        "suite_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest()
        if suite
        else None,
        "notice": "Local CPU inference on synthetic public FAQ. No Supabase/API calls. Manual evaluation set, not a guarantee of accuracy on new questions.",
        "results": [],
    }
    for position, case in enumerate(cases, 1):
        started = time.perf_counter()
        result = answer_from_faq(
            case["question"],
            articles,
            index,
            settings.jana_min_score,
            settings.jana_score_margin,
        )
        outcome = (
            "not_scored"
            if args.question
            else assess_answer(case, result, index.catalog, articles)
        )
        row = {
            "id": case.get("id", f"case-{position:03d}"),
            "category": case.get("category", "uncategorized"),
            "question": case["question"],
            "expected_card": case.get("card"),
            "expected": case.get("expected"),
            "result": result,
            "seconds": round(time.perf_counter() - started, 4),
            "outcome": outcome,
            "checks_passed": None if args.question else outcome == "pass",
        }
        report["results"].append(row)
        if row["checks_passed"] is False:
            print(f"FAIL [{outcome}]: " + case["question"])
    report["passed"] = sum(r["checks_passed"] is True for r in report["results"])
    report["total"] = sum(r["outcome"] != "not_scored" for r in report["results"])
    report["summary"] = summarize(report["results"])
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Report: {args.output.resolve()}")
    else:
        print(text)
    print(
        f"Passed: {report['passed']}/{report['total']}; model load: {report['load_seconds']} s"
    )
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
