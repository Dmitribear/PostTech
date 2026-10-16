"""Release checks use synthetic fixtures, never the real model or held-out suites."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.services.jana_errors import JanaUnavailable
from app.services.jana_local import FAQCatalog, refuse
from scripts import check_jana_release as release


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    root = tmp_path / "project"
    content = "A verified synthetic answer."
    article_id = "20000000-0000-4000-8000-000000000001"
    catalog_data = {"version": "test", "demo": False, "notice": "Only a unit fixture",
                    "cards": [{"id": "known", "article_id": article_id,
                               "source_sha256": hashlib.sha256(content.encode()).hexdigest(),
                               "questions": ["A known question?"], "excerpt": content}],
                    "unsupported_questions": ["An unknown question?"]}
    faq_path = root / "knowledge_base/faq.json"
    _save(faq_path, catalog_data)
    articles = [{"id": article_id, "content": content, "source_title": "Unit source", "active": True}]
    _save(root / "knowledge_base/demo/articles.json", {"articles": articles})
    for name, count in release.SUITES.items():
        # These invented questions do not read any repository evaluation data.
        cases = [{"id": f"{name}-{i}", "category": "unit",
                  "question": f"{'Answer' if i % 2 == 0 else 'Refuse'} {name} {i}",
                  **({"card": "known"} if i % 2 == 0 else {"expected": "refusal"})}
                 for i in range(count)]
        _save(root / f"knowledge_base/demo/{name}.json", {"name": name, "cases": cases})
    for name in release.RUNTIME_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic source for hashing\n", encoding="utf-8")
    catalog = FAQCatalog.model_validate(catalog_data)
    settings = SimpleNamespace(jana_faq_path=faq_path, jana_min_score=0.72, jana_score_margin=0.045)
    state = {"loads": 0, "answers": 0}

    def get_index(_settings):
        state["loads"] += 1
        return SimpleNamespace(catalog=catalog)

    def answer(question, _articles, _index, minimum, margin):
        state["answers"] += 1
        assert (minimum, margin) == (0.72, 0.045)
        if question.startswith("Refuse"):
            return refuse()
        return {"answer": content + " [1]", "mode": "excerpts", "grounded": True,
                "escalation_suggested": False,
                "sources": [{"id": article_id, "title": "Unit source",
                             "url": f"/api/v1/ai/sources/{article_id}", "excerpt": content}]}

    monkeypatch.setattr(release, "ROOT", root)
    monkeypatch.setattr(release, "get_settings", lambda: settings)
    monkeypatch.setattr(release, "get_index", get_index)
    monkeypatch.setattr(release, "answer_from_faq", answer)
    return SimpleNamespace(root=root, output=tmp_path / "reports", state=state,
                           settings=settings, catalog=catalog, answer=answer)


def _manifest(environment):
    return json.loads((environment.output / "manifest.json").read_text(encoding="utf-8"))


def test_release_contract_includes_every_frozen_suite():
    assert release.SUITES == {"acceptance_v1": 50, "acceptance_v2": 60, "acceptance_v3": 30,
                             "local_evaluation": 44, "local_holdout": 24, "request_status_v1": 20,
                             "profile_fix_v1": 20, "safety_v1": 35, "review_regression_v1": 2}
    assert sum(release.SUITES.values()) == 285


def test_all_suites_share_one_index_and_record_reproducible_inputs(environment):
    assert release.main(["--output-dir", str(environment.output)]) == 0
    assert environment.state == {"loads": 1, "answers": 285}
    manifest = _manifest(environment)
    assert manifest["complete"] is True
    assert manifest["passed"] == manifest["total"] == manifest["planned_total"] == 285
    assert manifest["errors"] == []
    assert manifest["source_preflight"] == {"checked_cards": 1, "issues": []}
    assert manifest["card_coverage"] == {"covered": ["known"], "missing": []}
    assert (manifest["min_score"], manifest["margin"]) == (0.72, 0.045)
    assert manifest["faq_sha256"] == hashlib.sha256(environment.settings.jana_faq_path.read_bytes()).hexdigest()
    assert set(manifest["runtime_sha256"]) == set(release.RUNTIME_FILES)
    assert manifest["runtime_sha256"]["app/services/jana_local.py"] == hashlib.sha256(
        (environment.root / "app/services/jana_local.py").read_bytes()).hexdigest()
    for name, count in release.SUITES.items():
        report = json.loads((environment.output / f"{name}.json").read_text(encoding="utf-8"))
        suite_path = environment.root / f"knowledge_base/demo/{name}.json"
        assert report["suite_sha256"] == manifest["suite_sha256"][name] == hashlib.sha256(suite_path.read_bytes()).hexdigest()
        assert report["passed"] == report["total"] == report["planned_total"] == count
        assert report["complete"] is True
        assert report["summary"]["outcomes"] == {"pass": count}


def test_wrong_answer_is_nonzero_even_when_every_suite_completed(environment, monkeypatch):
    def answer(question, *args):
        if question == "Answer acceptance_v1 0":
            return refuse()
        return environment.answer(question, *args)

    monkeypatch.setattr(release, "answer_from_faq", answer)
    assert release.run(environment.output) == 1
    manifest = _manifest(environment)
    assert manifest["complete"] is True
    assert manifest["passed"] == 284
    assert manifest["total"] == 285
    assert manifest["summary"]["outcomes"]["false_refusal"] == 1


@pytest.mark.parametrize("damage", ["missing", "truncated", "invalid_label"])
def test_missing_or_invalid_suite_cannot_be_silently_skipped(environment, damage):
    path = environment.root / "knowledge_base/demo/acceptance_v3.json"
    if damage == "missing":
        path.unlink()
    else:
        suite = json.loads(path.read_text(encoding="utf-8"))
        if damage == "truncated":
            suite["cases"].pop()
        else:
            suite["cases"][0]["card"] = "nonexistent"
        _save(path, suite)
    assert release.run(environment.output) == 2
    manifest = _manifest(environment)
    assert manifest["complete"] is False
    assert manifest["errors"][0]["stage"] == "validate acceptance_v3"
    assert environment.state == {"loads": 0, "answers": 0}
    assert manifest["total"] == 0
    assert manifest["planned_total"] == 285


def test_inference_error_preserves_partial_result_without_reporting_full_success(environment, monkeypatch):
    def answer(question, *args):
        if question == "Refuse acceptance_v1 1":
            raise JanaUnavailable("Do not log private exception details")
        return environment.answer(question, *args)

    monkeypatch.setattr(release, "answer_from_faq", answer)
    assert release.run(environment.output) == 2
    manifest = _manifest(environment)
    partial = json.loads((environment.output / "acceptance_v1.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["passed"] == manifest["total"] == 1
    assert partial["complete"] is False
    assert partial["planned_total"] == 50
    assert len(manifest["suites"]) == 1
    assert manifest["errors"][0]["type"] == "JanaUnavailable"
    assert "private exception" not in (environment.output / "manifest.json").read_text(encoding="utf-8")


def test_unavailable_model_is_nonzero_and_retains_preflight_fingerprints(environment, monkeypatch):
    def unavailable(_settings):
        raise JanaUnavailable("Unavailable")

    monkeypatch.setattr(release, "get_index", unavailable)
    assert release.run(environment.output) == 2
    manifest = _manifest(environment)
    assert manifest["model_loaded"] is False
    assert manifest["complete"] is False
    assert len(manifest["suite_sha256"]) == 9
    assert environment.state["answers"] == 0


@pytest.mark.parametrize("existing", ["manifest.json", "acceptance_v1.json"])
def test_existing_reports_are_preserved_without_explicit_overwrite(environment, existing):
    environment.output.mkdir()
    protected = environment.output / existing
    protected.write_text("Do not replace this historical report", encoding="utf-8")
    assert release.run(environment.output) == 2
    assert protected.read_text(encoding="utf-8") == "Do not replace this historical report"
    assert environment.state == {"loads": 0, "answers": 0}
    assert len(list(environment.output.iterdir())) == 1


def test_explicit_overwrite_replaces_old_reports(environment):
    environment.output.mkdir()
    (environment.output / "manifest.json").write_text("old report", encoding="utf-8")
    assert release.main(["--output-dir", str(environment.output), "--overwrite"]) == 0
    assert _manifest(environment)["complete"] is True


def test_source_change_during_run_invalidates_the_release(environment, monkeypatch):
    def answer(question, *args):
        if question == "Answer acceptance_v1 0":
            (environment.root / "app/services/jana_local.py").write_text("# Changed mid-run", encoding="utf-8")
        return environment.answer(question, *args)

    monkeypatch.setattr(release, "answer_from_faq", answer)
    assert release.run(environment.output) == 2
    manifest = _manifest(environment)
    assert manifest["passed"] == 285
    assert manifest["complete"] is False
    assert manifest["errors"] == [{"stage": "verify unchanged inputs", "type": "InputChanged", "file": "jana_local.py"}]


def test_stale_cached_catalog_is_rejected_before_answers(environment, monkeypatch):
    stale = environment.catalog.model_copy(update={"notice": "A previous cached catalog"})
    monkeypatch.setattr(release, "get_index", lambda _settings: SimpleNamespace(catalog=stale))
    assert release.run(environment.output) == 2
    assert _manifest(environment)["complete"] is False
    assert environment.state["answers"] == 0


@pytest.mark.parametrize("damage", ["missing", "stale", "duplicate", "inactive", "missing_excerpt"])
def test_all_sources_are_validated_before_model_load(environment, damage):
    path = environment.root / "knowledge_base/demo/articles.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if damage == "missing":
        data["articles"][0]["id"] = "20000000-0000-4000-8000-000000000099"
    elif damage == "stale":
        data["articles"][0]["content"] += " A changed qualification outside the excerpt."
    elif damage == "duplicate":
        data["articles"].append(dict(data["articles"][0]))
    elif damage == "inactive":
        data["articles"][0]["active"] = False
    elif damage == "missing_excerpt":
        data["articles"][0]["content"] = "A new article without the quoted text."
        faq = json.loads(environment.settings.jana_faq_path.read_text(encoding="utf-8"))
        faq["cards"][0]["source_sha256"] = hashlib.sha256(data["articles"][0]["content"].encode()).hexdigest()
        _save(environment.settings.jana_faq_path, faq)
    _save(path, data)
    assert release.run(environment.output) == 2
    manifest = _manifest(environment)
    assert manifest["complete"] is False
    assert manifest["source_preflight"] == {"checked_cards": 1, "issues": ["known"]}
    assert manifest["errors"][0]["stage"] == "validate sources"
    assert environment.state == {"loads": 0, "answers": 0}


def test_future_card_without_a_positive_case_cannot_pass_old_suites(environment):
    faq = json.loads(environment.settings.jana_faq_path.read_text(encoding="utf-8"))
    # This extra card has valid evidence, but none of the suites checks it.
    extra = {**faq["cards"][0], "id": "future_card", "questions": ["A future topic?"]}
    faq["cards"].append(extra)
    _save(environment.settings.jana_faq_path, faq)
    assert release.run(environment.output) == 2
    manifest = _manifest(environment)
    assert manifest["source_preflight"] == {"checked_cards": 2, "issues": []}
    assert manifest["card_coverage"] == {"covered": ["known"], "missing": ["future_card"]}
    assert manifest["errors"][0]["stage"] == "validate positive card coverage"
    assert environment.state == {"loads": 0, "answers": 0}


def test_future_uncovered_card_with_missing_source_fails_source_preflight(environment):
    faq = json.loads(environment.settings.jana_faq_path.read_text(encoding="utf-8"))
    extra = {**faq["cards"][0], "id": "future_card", "questions": ["A future topic?"],
             "article_id": "20000000-0000-4000-8000-000000000099"}
    faq["cards"].append(extra)
    _save(environment.settings.jana_faq_path, faq)
    assert release.run(environment.output) == 2
    manifest = _manifest(environment)
    assert manifest["source_preflight"] == {"checked_cards": 2, "issues": ["future_card"]}
    assert manifest["errors"][0]["stage"] == "validate sources"
    assert environment.state == {"loads": 0, "answers": 0}
