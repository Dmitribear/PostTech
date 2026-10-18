"""Keep the evaluation honest: bad evidence and missing labels cannot pass."""

import copy
import json
from pathlib import Path

import pytest
import argparse

from app.infrastructure.ai.jana_local import FAQCatalog, refuse
from scripts.evaluate_jana_local import assess_answer, summarize, validate_cases
from scripts.evaluate_jana_http import catalog_source_issues, local_api_url

ROOT = Path(__file__).resolve().parents[1]
CATALOG = FAQCatalog.model_validate_json(
    (ROOT / "knowledge_base/faq.json").read_text(encoding="utf-8")
)
ARTICLES = json.loads(
    (ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8")
)["articles"]


def valid_answer():
    card = CATALOG.cards[0]
    article = next(a for a in ARTICLES if a["id"] == str(card.article_id))
    return {
        "answer": "Демо: " + card.excerpt + " [1]",
        "mode": "excerpts",
        "grounded": True,
        "escalation_suggested": False,
        "sources": [
            {
                "id": str(card.article_id),
                "title": article["source_title"],
                "url": f"/api/v1/ai/local/sources/{card.article_id}",
                "excerpt": card.excerpt,
            }
        ],
    }


def test_evaluation_distinguishes_wrong_answers_from_safe_but_unhelpful_refusals():
    answer = valid_answer()
    assert assess_answer({"card": "leave_apply"}, answer, CATALOG, ARTICLES) == "pass"
    assert (
        assess_answer({"card": "advance_apply"}, answer, CATALOG, ARTICLES)
        == "wrong_card"
    )
    assert (
        assess_answer({"expected": "refusal"}, answer, CATALOG, ARTICLES)
        == "unexpected_answer"
    )
    assert (
        assess_answer({"card": "leave_apply"}, refuse(), CATALOG, ARTICLES)
        == "false_refusal"
    )
    assert assess_answer({"expected": "refusal"}, refuse(), CATALOG, ARTICLES) == "pass"


@pytest.mark.parametrize(
    "change",
    [
        "fabricated_suffix",
        "external_url",
        "title",
        "altered_article",
        "inactive_article",
    ],
)
def test_plausible_citation_is_not_enough_to_pass(change):
    answer, articles = valid_answer(), copy.deepcopy(ARTICLES)
    if change == "fabricated_suffix":
        answer["answer"] += " Отпуск всегда одобрят."
    elif change == "external_url":
        answer["sources"][0]["url"] = "https://example.invalid/source"
    elif change == "title":
        answer["sources"][0]["title"] = "Несуществующая политика"
    elif change == "altered_article":
        articles[0]["content"] += " Новое существенное условие."
    elif change == "inactive_article":
        articles[0]["active"] = False
    assert (
        assess_answer({"card": "leave_apply"}, answer, CATALOG, articles)
        == "invalid_evidence"
    )


def test_refusal_with_sources_or_grounded_flag_cannot_pass():
    bad = {**refuse(), "grounded": True}
    assert (
        assess_answer({"expected": "refusal"}, bad, CATALOG, ARTICLES)
        == "invalid_refusal"
    )
    assert (
        assess_answer({"expected": "refusal"}, {}, CATALOG, ARTICLES)
        == "invalid_response"
    )


@pytest.mark.parametrize(
    "case",
    [
        {"question": "Как оформить отпуск?"},
        {"question": "Как оформить отпуск?", "expected": "refusla"},
        {"question": "Как оформить отпуск?", "card": "missing"},
        {
            "question": "Как оформить отпуск?",
            "card": "leave_apply",
            "expected": "refusal",
        },
    ],
)
def test_missing_or_misspelled_expectations_are_rejected(case):
    with pytest.raises(ValueError):
        validate_cases([case], CATALOG)


def test_acceptance_questions_are_new_and_cover_every_card():
    suite = json.loads(
        (ROOT / "knowledge_base/demo/acceptance_v1.json").read_text(encoding="utf-8")
    )["cases"]
    normalize = lambda text: " ".join(text.split()).casefold()
    old_questions = {normalize(q) for card in CATALOG.cards for q in card.questions}
    old_questions.update(normalize(q) for q in CATALOG.unsupported_questions)
    for name in ("local_evaluation", "local_holdout"):
        previous = json.loads(
            (ROOT / f"knowledge_base/demo/{name}.json").read_text(encoding="utf-8")
        )["cases"]
        validate_cases(previous, CATALOG)
        old_questions.update(normalize(case["question"]) for case in previous)
    validate_cases(suite, CATALOG)
    assert len(suite) == 50
    assert {c["card"] for c in suite if "card" in c} == {c.id for c in CATALOG.cards}
    assert all(normalize(case["question"]) not in old_questions for case in suite)


def test_duplicate_case_ids_and_questions_are_rejected():
    case = {"id": "one", "question": "Вопрос для проверки", "expected": "refusal"}
    with pytest.raises(ValueError):
        validate_cases([case, {**case, "question": "Другой вопрос"}], CATALOG)
    with pytest.raises(ValueError):
        validate_cases([case, {**case, "id": "two"}], CATALOG)


@pytest.mark.parametrize(
    "name,count", [("acceptance_v2", 60), ("acceptance_v3", 30), ("safety_v1", 35)]
)
def test_release_questions_are_not_copied_into_search_examples(name, count):
    suite = json.loads(
        (ROOT / f"knowledge_base/demo/{name}.json").read_text(encoding="utf-8")
    )["cases"]
    validate_cases(suite, CATALOG)
    normalize = lambda text: " ".join(text.split()).casefold()
    indexed = {normalize(q) for card in CATALOG.cards for q in card.questions}
    indexed.update(normalize(q) for q in CATALOG.unsupported_questions)
    assert len(suite) == count
    assert all(normalize(case["question"]) not in indexed for case in suite)
    if name.startswith("acceptance_"):
        assert {case["card"] for case in suite if "card" in case} == {
            card.id for card in CATALOG.cards
        }


@pytest.mark.parametrize(
    "suite_name,expected_cards,refusals",
    [
        ("request_status_v1", {"request_status": 8}, 12),
        ("profile_fix_v1", {"profile_fix": 8, "profile_access": 1}, 11),
    ],
)
def test_topic_regression_questions_are_not_search_examples(
    suite_name, expected_cards, refusals
):
    suite = json.loads(
        (ROOT / f"knowledge_base/demo/{suite_name}.json").read_text(encoding="utf-8")
    )["cases"]
    validate_cases(suite, CATALOG)
    normalize = lambda text: " ".join(text.split()).casefold()
    indexed = {normalize(q) for card in CATALOG.cards for q in card.questions}
    indexed.update(normalize(q) for q in CATALOG.unsupported_questions)
    assert len(suite) == 20
    for card_id, count in expected_cards.items():
        assert sum(case.get("card") == card_id for case in suite) == count
    assert sum(case.get("expected") == "refusal" for case in suite) == refusals
    assert all(normalize(case["question"]) not in indexed for case in suite)


def test_unlabelled_exploration_does_not_inflate_report_score():
    rows = [
        {"outcome": "not_scored", "category": "exploratory"},
        {
            "outcome": "false_refusal",
            "category": "typo",
            "expected_card": "leave_apply",
        },
        {"outcome": "pass", "category": "off_topic", "expected": "refusal"},
    ]
    report = summarize(rows)
    assert report["supported"] == {"passed": 0, "total": 1}
    assert report["refusals"] == {"passed": 1, "total": 1}
    assert "exploratory" not in report["categories"]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/v1",
        "http://127.0.0.1.evil.invalid/api/v1",
        "http://user:password@127.0.0.1:8000/api/v1",
        "http://127.0.0.1:8000/api/v1?token=secret",
        "http://127.0.0.1:8000/wrong-path",
    ],
)
def test_http_runner_wont_send_test_credentials_outside_local_api(url):
    with pytest.raises(argparse.ArgumentTypeError):
        local_api_url(url)


def test_http_runner_accepts_local_api_with_or_without_trailing_slash():
    assert (
        local_api_url("http://127.0.0.1:5173/api/v1/") == "http://127.0.0.1:5173/api/v1"
    )


def test_http_preflight_accepts_matching_sources_for_every_card():
    assert catalog_source_issues(CATALOG, ARTICLES) == []


@pytest.mark.parametrize(
    "change", ["outside_quote", "missing", "duplicate", "inactive"]
)
def test_http_preflight_finds_stale_cards_even_without_question_results(change):
    articles = copy.deepcopy(ARTICLES)
    card = next(card for card in CATALOG.cards if card.id == "request_status")
    article = next(a for a in articles if a["id"] == str(card.article_id))
    if change == "outside_quote":
        article["content"] += " Изменились условия рассмотрения."
        assert card.excerpt in article["content"]
    elif change == "missing":
        articles.remove(article)
    elif change == "duplicate":
        articles.append(copy.deepcopy(article))
    elif change == "inactive":
        article["active"] = False
    assert catalog_source_issues(CATALOG, articles) == ["request_status"]
