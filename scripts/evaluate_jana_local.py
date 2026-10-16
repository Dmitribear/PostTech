"""Offline evaluation with the real local model; no API calls or downloads.

python -m scripts.evaluate_jana_local --output .venv/jana-local-evaluation.json
python -m scripts.evaluate_jana_local --question "Куда подать заявление на отпуск?"
"""

import argparse
import json
import time
from pathlib import Path

from app.core.config import get_settings
from app.services.jana_errors import JanaUnavailable
from app.services.jana_local import answer_from_faq, get_index
from app.services.local_embeddings import MODEL_ID, REVISION

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question")
    parser.add_argument("--cases", type=Path, default=ROOT / "knowledge_base/demo/local_evaluation.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    started = time.perf_counter()
    try:
        index = get_index(settings)
    except JanaUnavailable as exc:
        print(f"Local model unavailable: {exc}")
        return 2
    articles = json.loads((ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8"))["articles"]
    cases = [{"question": args.question}] if args.question else json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    report = {"model": MODEL_ID, "revision": REVISION, "min_score": settings.jana_min_score,
              "margin": settings.jana_score_margin, "load_seconds": round(time.perf_counter() - started, 3),
              "notice": "Local CPU inference. Curated demo test set, not a guarantee of accuracy on new questions.", "results": []}
    for case in cases:
        started = time.perf_counter()
        result = answer_from_faq(case["question"], articles, index, settings.jana_min_score, settings.jana_score_margin)
        row = {"question": case["question"], "result": result, "seconds": round(time.perf_counter() - started, 4)}
        if "card" in case:
            expected = next(c for c in index.catalog.cards if c.id == case["card"])
            row["checks_passed"] = (result["mode"] == "excerpts" and len(result["sources"]) == 1
                                    and result["sources"][0]["excerpt"] == expected.excerpt
                                    and result["sources"][0]["id"] == str(expected.article_id))
        elif case.get("expected") == "refusal":
            row["checks_passed"] = result["mode"] == "refusal" and not result["sources"]
        for source in result["sources"]:
            original = next(a for a in articles if a["id"] == source["id"])
            assert source["excerpt"] in original["content"]
        report["results"].append(row)
        if not row.get("checks_passed", True):
            print("FAIL: " + case["question"])
    report["passed"] = sum(r.get("checks_passed", True) for r in report["results"])
    report["total"] = len(cases)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Report: {args.output.resolve()}")
    else:
        print(text)
    print(f"Passed: {report['passed']}/{report['total']}; model load: {report['load_seconds']} s")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
