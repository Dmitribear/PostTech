import argparse
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from app.services.jana_evidence import prepare_evidence, select_excerpts
from app.services.jana_intent import BOUNDARY_MESSAGES, CLARIFICATION_MESSAGES
from app.services.jana_reader import unavailable_evidence
from scripts.evaluate_jana_reader import inspect_response, local_api_url, source_issues, validate_cases
from scripts import evaluate_jana_reader as runner


ARTICLES = [{"id": "40000000-0000-4000-8000-000000000001", "title": "Общее правило",
             "source_title": "Инструкция", "content": "Материал доступен после назначения. HR назначает курс.", "active": True}]


def answer(kind="answer"):
    bundle = prepare_evidence(ARTICLES)
    sources = select_excerpts(bundle, [bundle.spans[0].id])
    return {"answer": BOUNDARY_MESSAGES[kind] + "\n\n" + sources[0]["excerpt"] + " [1]",
            "sources": sources, "grounded": True, "escalation_suggested": kind != "answer", "mode": "excerpts"}


@pytest.mark.parametrize("kind", ["answer", "partial", "action", "personal", "injection"])
def test_authentic_quotes_with_reviewed_boundaries_pass_integrity_only(kind):
    assert inspect_response(answer(kind), ARTICLES) == "pass"


def test_unrelated_authentic_quote_still_needs_separate_semantic_review():
    # inspect_response deliberately has no question/gold argument: authenticity
    # cannot establish whether a citation answers a particular user question.
    assert inspect_response(answer(), ARTICLES) == "pass"


def test_demo_notice_is_required_for_demo_sources_and_not_accepted_for_real_sources():
    result = answer()
    demo_articles = [{**ARTICLES[0], "source_title": "Демо: инструкция"}]
    result["sources"][0]["title"] = demo_articles[0]["source_title"]
    assert inspect_response(result, demo_articles) == "invalid_framing"
    result["answer"] = "Демонстрационные материалы:" + result["answer"]
    assert inspect_response(result, demo_articles) == "pass"
    result["sources"][0]["title"] = ARTICLES[0]["source_title"]
    assert inspect_response(result, ARTICLES) == "invalid_framing"


@pytest.mark.parametrize("change", ["invented_fact", "external_url", "source_title", "inexact_quote", "duplicate", "unknown_id"])
def test_plausible_looking_source_or_generated_assertion_cannot_pass(change):
    result = answer()
    if change == "invented_fact":
        result["answer"] += " Всегда дадут разрешение."
    elif change == "external_url":
        result["sources"][0]["url"] = "https://example.invalid/source"
    elif change == "source_title":
        result["sources"][0]["title"] = "Другая инструкция"
    elif change == "inexact_quote":
        result["sources"][0]["excerpt"] += " Нет ограничений."
    elif change == "duplicate":
        result["sources"].append(copy.deepcopy(result["sources"][0]))
    else:
        result["sources"][0]["id"] = "40000000-0000-4000-8000-000000000002"
    assert inspect_response(result, ARTICLES) != "pass"


def test_unknown_refusal_and_non_escalating_clarification_are_valid():
    assert inspect_response(unavailable_evidence(), ARTICLES) == "pass"
    for text in CLARIFICATION_MESSAGES.values():
        if text:
            refusal = {"answer": text, "sources": [], "grounded": False,
                       "escalation_suggested": False, "mode": "refusal"}
            assert inspect_response(refusal, ARTICLES) == "pass"
            assert inspect_response({**refusal, "escalation_suggested": True}, ARTICLES) != "pass"


@pytest.mark.parametrize("change", [{"grounded": False}, {"grounded": 1}, {"mode": "generated"},
                                   {"escalation_suggested": True}, {"untrusted": "extra"}])
def test_inconsistent_contract_cannot_pass(change):
    assert inspect_response({**answer(), **change}, ARTICLES) != "pass"


def test_refusal_cannot_hide_factual_answer_or_sources():
    assert inspect_response({**unavailable_evidence(), "answer": "Вы получили аванс."}, ARTICLES) != "pass"
    assert inspect_response({**unavailable_evidence(), "sources": answer()["sources"]}, ARTICLES) != "pass"


def test_inactive_or_missing_original_cannot_validate_quote():
    assert inspect_response(answer(), []) != "pass"
    assert inspect_response(answer(), [{**ARTICLES[0], "active": False}]) != "pass"
    assert inspect_response(answer(), ARTICLES + ARTICLES) != "pass"


def test_preflight_detects_changes_outside_quote_and_missing_sources():
    assert source_issues(ARTICLES, ARTICLES) == []
    changed = [{**ARTICLES[0], "content": ARTICLES[0]["content"] + " Новое исключение."}]
    assert source_issues(ARTICLES, changed) == [ARTICLES[0]["id"]]
    assert source_issues(ARTICLES, []) == [ARTICLES[0]["id"]]
    extra = {**ARTICLES[0], "id": "40000000-0000-4000-8000-000000000002"}
    assert source_issues(ARTICLES, ARTICLES + [extra]) == [extra["id"]]


def test_complete_inventory_reads_only_published_knowledge_with_overflow_detection(monkeypatch):
    calls = []

    class Query:
        def __getattr__(self, method):
            def record(*args):
                calls.append((method, args))
                return SimpleNamespace(data=ARTICLES) if method == "execute" else self
            return record

    monkeypatch.setattr(runner, "get_supabase_client", Query)
    assert runner.active_inventory() == ARTICLES
    assert calls == [("table", ("knowledge_articles",)),
                     ("select", ("id,title,content,source_title",)), ("eq", ("active", True)),
                     ("order", ("id",)), ("limit", (101,)), ("execute", ())]


@pytest.mark.parametrize("url", ["https://127.0.0.1/api/v1", "http://localhost.example/api/v1",
                               "http://user:pass@localhost/api/v1", "http://localhost/api/v1?key=secret"])
def test_credentials_are_restricted_to_loopback_api_urls(url):
    with pytest.raises(argparse.ArgumentTypeError):
        local_api_url(url)


def test_unlabelled_duplicate_or_card_only_gold_is_rejected():
    case = {"id": "A", "question": "Где материал?", "expected_behavior": "supported",
            "required_facts": ["Материал доступен после назначения."]}
    assert validate_cases({"cases": [case]}) == [case]
    with pytest.raises(ValueError):
        validate_cases({"cases": [case, {**case, "id": "B"}]})
    with pytest.raises(ValueError):
        validate_cases({"cases": [{**case, "required_facts": []}]})
    with pytest.raises(ValueError):
        validate_cases({"cases": [{"id": "A", "question": "Где материал?", "card": "legacy"}]})


def _fake_run(monkeypatch, tmp_path, count=2):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [
        {"id": str(i), "question": f"Вопрос номер {i}", "expected_behavior": "supported", "required_facts": ["Факт"]}
        for i in range(count)
    ]}), encoding="utf-8")
    output = tmp_path / "first.json"
    monkeypatch.setattr(sys, "argv", ["evaluate_jana_reader", "--mode", "local", "--cases", str(cases),
                                     "--development", "--output", str(output)])
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(jana_reader_model="fixture"))
    monkeypatch.setattr(runner, "LocalReader", lambda _settings: object())
    return cases, output


def test_failed_run_preserves_completed_rows_without_secrets_and_cannot_overwrite(monkeypatch, tmp_path):
    _cases, output = _fake_run(monkeypatch, tmp_path)
    calls = 0

    def fail_second(*_args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("DO-NOT-LEAK-SECRET")
        return unavailable_evidence()

    monkeypatch.setattr(runner, "answer_from_knowledge", fail_second)
    assert runner.main() == 2
    saved_text = output.read_text(encoding="utf-8")
    saved = json.loads(saved_text)
    journal = output.with_suffix(".json.jsonl").read_text(encoding="utf-8")
    assert saved["total"] == 1 and not saved["completed"]
    assert saved["development"] and not saved["blind_candidate"]
    assert saved["error"] == {"type": "RuntimeError", "status": None, "case_id": "1"}
    assert "DO-NOT-LEAK-SECRET" not in saved_text + journal
    assert len([line for line in journal.splitlines() if json.loads(line)["event"] == "case"]) == 1
    with pytest.raises(SystemExit) as stopped:
        runner.main()
    assert stopped.value.code == 2
    assert output.read_text(encoding="utf-8") == saved_text


def test_changed_gold_during_inference_invalidates_run(monkeypatch, tmp_path):
    cases, output = _fake_run(monkeypatch, tmp_path, count=1)

    def change_gold(*_args):
        cases.write_text(cases.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return unavailable_evidence()

    monkeypatch.setattr(runner, "answer_from_knowledge", change_gold)
    assert runner.main() == 2
    saved = json.loads(output.read_text(encoding="utf-8"))
    expected_path = cases.relative_to(runner.ROOT).as_posix() if cases.is_relative_to(runner.ROOT) else str(cases)
    assert saved["completed"] and saved["changed_inputs"] == [expected_path]
