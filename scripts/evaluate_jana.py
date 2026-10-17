"""Opt-in live-model evaluation using only the curated, fictional local KB.

python -m scripts.evaluate_jana --question "Хочу уйти отдыхать: где указать даты?"
python -m scripts.evaluate_jana --limit 19 --output .venv/jana-live-evaluation.json
Requires OPENAI_API_KEY in the environment or .env; calls the paid API explicitly.
"""

import argparse
import json
from pathlib import Path

from app.infrastructure.config import get_settings
from app.infrastructure.ai.jana_agent import (
    JanaUnavailable,
    OpenAIReasoner,
    answer_from_articles,
)

ROOT = Path(__file__).resolve().parents[1]


def outcome_matches(case: dict, result: dict) -> bool:
    """Mechanical checks only; inspect the report for semantic correctness."""
    expected = case["expected"]
    if expected == "answer":
        return (
            result["grounded"]
            and not result["escalation_suggested"]
            and set(case["source_ids"]) <= {s["id"] for s in result["sources"]}
        )
    if expected == "partial_answer_with_escalation":
        return result["grounded"] and result["escalation_suggested"]
    return (
        result["mode"] == "refusal"
        and not result["sources"]
        and result["escalation_suggested"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    articles = json.loads(
        (ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8")
    )["articles"]
    cases = json.loads(
        (ROOT / "knowledge_base/demo/evaluation.json").read_text(encoding="utf-8")
    )["cases"]
    if args.question:
        cases = [{"question": args.question}]
    else:
        cases = cases[: args.limit]
    try:
        reasoner = OpenAIReasoner(get_settings())
    except JanaUnavailable:
        print(
            "Configure OPENAI_API_KEY in the local .env; no model requests were made."
        )
        return 2
    report = {
        "model": reasoner.model,
        "notice": "Live API; synthetic data. Checks do not establish semantic accuracy. Review each answer.",
        "results": [],
    }
    failed = False
    try:
        for index, case in enumerate(cases, 1):
            try:
                result = answer_from_articles(case["question"], articles, reasoner)
            except JanaUnavailable:
                report["results"].append(
                    {"question": case["question"], "error": "AI unavailable"}
                )
                failed = True
                print(
                    f"{index}/{len(cases)}: AI unavailable; stopping to avoid repeated calls."
                )
                break
            row = {"question": case["question"], "result": result}
            if "expected" in case:
                row.update(
                    expected=case["expected"],
                    checks_passed=outcome_matches(case, result),
                )
                failed = failed or not row["checks_passed"]
            report["results"].append(row)
            print(
                f"{index}/{len(cases)}: {result['mode']}, grounded={result['grounded']}, escalation={result['escalation_suggested']}"
            )
    finally:
        reasoner.close()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Report: {args.output.resolve()}")
    else:
        print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
