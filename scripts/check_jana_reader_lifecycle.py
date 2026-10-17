"""Live local-model check: a new fact, a changed fact, and an unpublished source.

Uses an in-memory synthetic article only. Never writes to Supabase or the FAQ.
This is a development check, not part of the unseen question set.
"""

import argparse
import json
from pathlib import Path

from app.infrastructure.config import get_settings
from app.infrastructure.ai.jana_reader import LocalReader, answer_from_knowledge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    root = Path(__file__).resolve().parents[1]
    base = json.loads(
        (root / "knowledge_base/demo/articles.json").read_text(encoding="utf-8")
    )["articles"]
    article = {
        "id": "40000000-0000-4000-8000-000000000991",
        "active": True,
        "title": "Временный пропуск",
        "source_title": "Демо: тест добавления знаний",
        "content": "В тестовой организации временный пропуск для гостя запрашивают за два рабочих дня до визита.",
    }
    changed = {**article, "content": article["content"].replace("два", "пять")}
    question = (
        "За сколько рабочих дней до визита нужно попросить временный пропуск для гостя?"
    )
    reader = LocalReader(get_settings())
    checks = []
    for name, rows, expected in [
        ("new_published_article", base + [article], article["content"]),
        ("changed_fact", base + [changed], changed["content"]),
        ("unpublished_article", base + [{**changed, "active": False}], None),
    ]:
        answer = answer_from_knowledge(question, rows, reader)
        passed = (
            (
                answer["mode"] == "excerpts"
                and expected in answer["answer"]
                and any(s["id"] == article["id"] for s in answer["sources"])
            )
            if expected
            else (
                answer["mode"] == "refusal"
                and not answer["sources"]
                and not answer["grounded"]
            )
        )
        checks.append(
            {"check": name, "expected": expected, "passed": passed, "result": answer}
        )
        print(name, passed, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            {"question": question, "synthetic_source": article, "checks": checks},
            stream,
            ensure_ascii=False,
            indent=2,
        )
    return 0 if all(c["passed"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
