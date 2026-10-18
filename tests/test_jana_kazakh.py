import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.ai.jana_actions import ACTION_ROUTES, KAZAKH_UI_CAPTIONS, action_buttons, localize_ui_captions
from app.infrastructure.ai.jana_conditions import retain_portal_terms
from app.infrastructure.ai.jana_scope import classify_scope


ROOT = Path(__file__).resolve().parents[1]
ARTICLES = json.loads((ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8"))["articles"]
COURSE = next(a for a in ARTICLES if a["id"].endswith("000000000007"))
RETRY = next(a for a in ARTICLES if a["id"].endswith("000000000013"))


@pytest.mark.parametrize("answer", [
    "Онда прогресс, нәтиже және өту мерзімі көрсетіледі.",
    "Егер курс тағайындалса, оның мерзімі көрсетіледі.",
    "Өту мерзімі көрсетіледі. Барлық сабақтарды аяқтаңыз.",
])
def test_deadline_keeps_source_condition_even_with_an_unrelated_if(answer):
    result = retain_portal_terms(answer, [COURSE], "kk")
    assert "мерзімі (егер белгіленсе)" in result
    assert retain_portal_terms(result, [COURSE], "kk") == result
    if "Барлық сабақтарды аяқтаңыз." in answer:
        assert result.endswith("Барлық сабақтарды аяқтаңыз.")


def test_existing_deadline_condition_is_not_repeated():
    answer = "Курс мерзімі белгіленген болса, ол карточкада көрсетіледі."
    assert retain_portal_terms(answer, [COURSE], "kk") == answer


def test_catalogue_visibility_is_not_proof_of_assignment():
    text = "Курс тек осы бөлімде көрсетілсе ғана тағайындалған болып саналады."
    result = retain_portal_terms(text, [COURSE], "kk")
    assert result == "Курстың каталогта болуы оның сізге тағайындалғанын білдірмейді."
    assert retain_portal_terms(result, [COURSE], "kk") == result
    assert retain_portal_terms(text, [], "kk") == text
    simple = "Сізге тағайындалған курстар осы бөлімде көрсетіледі."
    assert retain_portal_terms(simple, [COURSE], "kk") == simple


@pytest.mark.parametrize("word", ["мерзімдері", "мерзімдерін", "мерзімін"])
def test_course_deadline_inflections_keep_the_condition(word):
    answer = f"Курс карточкасында {word} қараңыз."
    result = retain_portal_terms(answer, [COURSE], "kk")
    assert word + " (егер белгіленсе)" in result
    assert retain_portal_terms(result, [COURSE], "kk") == result


def test_deadline_correction_needs_current_evidence_and_does_not_invent_dates():
    answer = "Курс мерзімі көрсетіледі."
    changed = {**COURSE, "content": "Курс имеет обязательный срок."}
    assert retain_portal_terms(answer, [], "kk") == answer
    assert retain_portal_terms(answer, [changed], "kk") == answer
    excerpt = {**COURSE, "full_content": COURSE["content"], "content": "Назначенные курсы."}
    assert "егер белгіленсе" in retain_portal_terms(answer, [excerpt], "kk")


@pytest.mark.parametrize("action_id", ACTION_ROUTES)
def test_all_nine_api_button_labels_match_the_kazakh_ui(action_id):
    translations = json.loads((ROOT / "frontend/src/shared/lib/kk.json").read_text(encoding="utf-8"))
    ru_label, href = ACTION_ROUTES[action_id]
    button = action_buttons([action_id], role="hr_admin", language="kk")[0]
    assert button == {"id": action_id, "label": translations[ru_label], "href": href}
    assert button["label"] != ru_label


def test_translation_does_not_grant_approval_access_or_change_navigation():
    assert action_buttons(["requests_review"], role="worker", language="kk") == []
    assert action_buttons(["unknown"], role="hr_admin", language="kk") == []
    for role in ("manager", "director", "hr_admin"):
        assert action_buttons(["requests_review"], role=role, language="kk")[0]["href"] == "/requests?scope=review"


@pytest.mark.parametrize("opening,closing", [("«", "»"), ('"', '"'), ("“", "”")])
def test_quoted_ui_captions_follow_portal_dictionary_without_altering_conditions(opening, closing):
    text = "Тек " + opening + "На согласовании" + closing + " мәртебесінде. " + opening + "Завершено" + closing
    assert localize_ui_captions(text, "kk") == "Тек " + opening + "Келісуде" + closing + " мәртебесінде. " + opening + "Аяқталды" + closing
    assert localize_ui_captions(text, "ru") == text


def test_localized_ui_captions_match_existing_portal_terms():
    translations = json.loads((ROOT / "frontend/src/shared/lib/kk.json").read_text(encoding="utf-8"))
    for label, translated in KAZAKH_UI_CAPTIONS.items():
        if label in translations:
            assert translated == translations[label]


@pytest.mark.parametrize("text", [
    "Портал әрекеттер санына немесе міндетті үзіліске шектеу қоймайды.",
    "Әрекеттер саны шектелмейді, бірақ міндетті үзіліс талап етіледі.",
    "Сәтсіз әрекеттер санына шектеу жоқ. Әрекеттер арасында міндетті үзіліс жоқ.",
])
def test_retry_limits_preserve_two_separate_negations_and_lesson_requirement(text):
    result = retain_portal_terms(text, [RETRY], "kk")
    assert result.count("Сәтсіз әрекеттер санына шектеу жоқ.") == 1
    assert result.count("Әрекеттер арасында міндетті үзіліс жоқ.") == 1
    assert "барлық сабақтар мен материалды аяқтау қажет" in result
    assert "талап етіледі" not in result
    assert retain_portal_terms(result, [RETRY], "kk") == result


def test_retry_correction_requires_evidence_and_preserves_other_conditions():
    text = "Тестті қайталауға болады. Барлық сабақтар тестке дейін аяқталуы тиіс."
    assert retain_portal_terms(text, [RETRY], "kk") == text
    changed = {**RETRY, "content": "Попытки и условия курса задаёт HR."}
    unknown = "Үзіліс талап етіледі."
    assert retain_portal_terms(unknown, [changed], "kk") == unknown


@pytest.mark.parametrize("payload,expected_intent", [
    ({"intent": "information", "actions": ["profile"], "question_ru": "Как исправить телефон в профиле?"}, "information"),
    ({"intent": "out_of_scope", "actions": [], "question_ru": ""}, "out_of_scope"),
    ({"intent": "personal_data", "actions": ["profile"], "question_ru": ""}, "personal_data"),
    ({"intent": "information", "actions": ["profile"], "question_ru": ""}, "out_of_scope"),
    ({"intent": "information", "actions": ["profile"]}, "out_of_scope"),
    ({"intent": "information", "actions": ["profile"], "question_ru": 123}, "out_of_scope"),
    ({"intent": "information", "actions": ["profile"], "question_ru": "x" * 2001}, "out_of_scope"),
])
def test_kazakh_scope_requires_complete_translation_without_weakening_intent(payload, expected_intent):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            content=json.dumps(payload), refusal=None,
        ))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    question = "Профильдегі телефон нөмірін қалай өзгертемін?"
    result = classify_scope(client, "test", question, language="kk")
    assert result["intent"] == expected_intent
    assert json.loads(calls[0]["messages"][1]["content"])["question"] == question
    assert "question_ru" in calls[0]["response_format"]["json_schema"]["schema"]["required"]
    if expected_intent != "information":
        assert result["actions"] == []
        assert "question_ru" not in result
