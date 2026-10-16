"""Run every frozen local Jana suite with one model and preserve a release record.

python -m scripts.check_jana_release --output-dir docs/reports/release-YYYY-MM-DD
Exit codes: 0 all checks pass, 1 answer mismatches, 2 incomplete/error/changed inputs.
"""

import argparse
import hashlib
import json
import platform
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app.core.config import get_settings
from app.services.jana_local import FAQCatalog, answer_from_faq, get_index
from app.services.local_embeddings import MODEL_FILES, MODEL_ID, REVISION
from scripts.evaluate_jana_local import assess_answer, summarize, validate_cases

ROOT = Path(__file__).resolve().parents[1]
# Counts make accidental truncation visible. Intentional suite revisions must
# update this release contract; historical reports retain their input hashes.
SUITES = {
    "acceptance_v1": 50,
    "acceptance_v2": 60,
    "acceptance_v3": 30,
    "local_evaluation": 44,
    "local_holdout": 24,
    "request_status_v1": 20,
    "profile_fix_v1": 20,
    "safety_v1": 35,
    "review_regression_v1": 2,
}
RUNTIME_FILES = (
    "app/core/config.py", "app/schemas/jana.py",
    "app/services/jana_local.py", "app/services/jana_guardrails.py",
    "app/services/jana_text.py", "app/services/local_embeddings.py",
    "app/services/jana_errors.py", "scripts/evaluate_jana_local.py",
    "scripts/check_jana_release.py",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, value: dict, overwrite: bool) -> None:
    with path.open("w" if overwrite else "x", encoding="utf-8") as target:
        target.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _source_issues(catalog: FAQCatalog, articles: list[dict]) -> list[str]:
    """Validate every card, including cards no question happened to select."""
    issues = []
    for card in catalog.cards:
        matches = [article for article in articles
                   if str(article["id"]) == str(card.article_id) and article.get("active") is not False]
        if len(matches) != 1:
            issues.append(card.id)
            continue
        content = matches[0].get("content")
        if (not isinstance(content, str) or card.excerpt not in content
                or _sha256(content.encode("utf-8")) != card.source_sha256):
            issues.append(card.id)
    return issues


def run(output_dir: Path, *, overwrite: bool = False) -> int:
    """Run in a fresh process; never contact Supabase or any inference API."""
    destinations = [output_dir / f"{name}.json" for name in SUITES]
    destinations.append(output_dir / "manifest.json")
    if not overwrite and any(path.exists() for path in destinations):
        print("Output reports already exist; choose another directory or pass --overwrite.")
        return 2
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Cannot create output directory: {type(exc).__name__}")
        return 2

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "execution": "local_cpu_demo_articles",
        "model": MODEL_ID, "revision": REVISION,
        "model_files_sha256": MODEL_FILES,
        "model_loaded": False, "python": platform.python_version(),
        "planned_suites": list(SUITES), "planned_total": sum(SUITES.values()),
        "suites": [], "errors": [],
        "notice": "Synthetic FAQ regression results, not a guarantee on unseen questions. No HTTP or database calls.",
    }
    fingerprints: dict[Path, str] = {}
    all_rows = []
    stage = "load settings"

    def read(path: Path) -> bytes:
        data = path.read_bytes()
        fingerprints[path] = _sha256(data)
        return data

    try:
        settings = get_settings()
        manifest.update(min_score=settings.jana_min_score, margin=settings.jana_score_margin)
        stage = "read FAQ and articles"
        catalog = FAQCatalog.model_validate_json(read(settings.jana_faq_path))
        article_path = ROOT / "knowledge_base/demo/articles.json"
        articles = json.loads(read(article_path))["articles"]
        if not isinstance(articles, list) or not articles:
            raise ValueError("Expected non-empty articles")
        manifest.update(faq_sha256=fingerprints[settings.jana_faq_path],
                        articles_sha256=fingerprints[article_path])
        stage = "validate sources"
        manifest["source_preflight"] = {"checked_cards": len(catalog.cards),
                                        "issues": _source_issues(catalog, articles)}
        if manifest["source_preflight"]["issues"]:
            raise ValueError("Every card requires one active matching source and a verified excerpt")
        stage = "fingerprint runtime"
        manifest["runtime_sha256"] = {name: _sha256(read(ROOT / name)) for name in RUNTIME_FILES}
        manifest["packages"] = {}
        for package in ("numpy", "onnxruntime", "tokenizers", "pydantic"):
            try:
                manifest["packages"][package] = version(package)
            except PackageNotFoundError:
                manifest["packages"][package] = None

        suites = {}
        manifest["suite_sha256"] = {}
        for name, count in SUITES.items():
            stage = f"validate {name}"
            suite_path = ROOT / f"knowledge_base/demo/{name}.json"
            suite = json.loads(read(suite_path))
            validate_cases(suite["cases"], catalog)
            if len(suite["cases"]) != count:
                raise ValueError("Unexpected number of cases")
            suites[name] = suite
            manifest["suite_sha256"][name] = fingerprints[suite_path]

        stage = "validate positive card coverage"
        covered = {case["card"] for suite in suites.values() for case in suite["cases"] if "card" in case}
        missing = {card.id for card in catalog.cards} - covered
        manifest["card_coverage"] = {"covered": sorted(covered), "missing": sorted(missing)}
        if missing:
            raise ValueError("Every card requires a positive evaluation case")

        stage = "load local model"
        started = time.perf_counter()
        index = get_index(settings)
        if index.catalog.model_dump() != catalog.model_dump():
            raise ValueError("Loaded index does not match the fingerprinted FAQ")
        manifest.update(model_loaded=True, load_seconds=round(time.perf_counter() - started, 3))

        for name, suite in suites.items():
            rows = []
            for position, case in enumerate(suite["cases"], 1):
                stage = f"evaluate {name} case {position}"
                try:
                    started = time.perf_counter()
                    answer = answer_from_faq(case["question"], articles, index,
                                             settings.jana_min_score, settings.jana_score_margin)
                    outcome = assess_answer(case, answer, catalog, articles)
                    rows.append({
                        "id": case.get("id", f"case-{position:03d}"),
                        "category": case.get("category", "uncategorized"),
                        "question": case["question"], "expected_card": case.get("card"),
                        "expected": case.get("expected"), "result": answer, "outcome": outcome,
                        "checks_passed": outcome == "pass",
                        "seconds": round(time.perf_counter() - started, 4),
                    })
                except Exception as exc:
                    # Exception values can contain config values. Record only
                    # their class and the public evaluation stage.
                    manifest["errors"].append({"stage": stage, "type": type(exc).__name__})
                    break
            report = {key: value for key, value in manifest.items()
                      if key not in {"suites", "errors", "planned_suites", "planned_total", "suite_sha256"}}
            report.update(suite_name=suite.get("name", name),
                          suite_sha256=manifest["suite_sha256"][name],
                          planned_total=SUITES[name], complete=len(rows) == SUITES[name],
                          total=len(rows), passed=sum(row["checks_passed"] for row in rows),
                          results=rows, summary=summarize(rows), errors=list(manifest["errors"]))
            stage = f"write {name} report"
            _write(output_dir / f"{name}.json", report, overwrite)
            manifest["suites"].append({"name": name, "report": f"{name}.json",
                                      **{key: report[key] for key in ("complete", "passed", "total", "planned_total")}})
            all_rows.extend(rows)
            print(f"{name}: {report['passed']}/{report['planned_total']}; complete={report['complete']}")
            if manifest["errors"]:
                break

        stage = "verify unchanged inputs"
        for path, digest in fingerprints.items():
            if _sha256(path.read_bytes()) != digest:
                manifest["errors"].append({"stage": stage, "type": "InputChanged", "file": path.name})
    except Exception as exc:
        manifest["errors"].append({"stage": stage, "type": type(exc).__name__})

    manifest.update(total=len(all_rows), passed=sum(row["checks_passed"] for row in all_rows),
                    summary=summarize(all_rows))
    manifest["complete"] = (not manifest["errors"] and len(manifest["suites"]) == len(SUITES)
                            and manifest["total"] == manifest["planned_total"])
    code = 2 if not manifest["complete"] else (0 if manifest["passed"] == manifest["total"] else 1)
    manifest["exit_code"] = code
    try:
        _write(output_dir / "manifest.json", manifest, overwrite)
    except OSError as exc:
        print(f"Cannot write manifest: {type(exc).__name__}")
        return 2
    print(f"Release: {manifest['passed']}/{manifest['planned_total']}; complete={manifest['complete']}; exit={code}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace reports from a previous run")
    args = parser.parse_args(argv)
    return run(args.output_dir, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
