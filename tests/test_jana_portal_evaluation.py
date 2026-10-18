import json
from pathlib import Path
import re

import pytest

from scripts.verify_jana_portal import evaluate_answer


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    case["id"]: case
    for case in json.loads((ROOT / "evals/jana_portal_questions.json").read_text(encoding="utf-8"))
}


def condition_result(case_id: str, condition_id: str, answer: str) -> bool:
    checks = evaluate_answer(CASES[case_id], {"answer": answer}, require_generation=False)
    return checks["condition:" + condition_id]


def test_all_corpus_patterns_compile_without_double_escaping_or_control_characters():
    for case in CASES.values():
        for condition in case.get("conditions", []):
            for field in ("any_patterns", "when_any", "none_patterns"):
                for pattern in condition.get(field, []):
                    assert "\\\\" not in pattern
                    assert not any(ord(character) < 32 for character in pattern)
                    re.compile(pattern)


@pytest.mark.parametrize("answer,expected", [
    ("Руководитель видит только прямых подчинённых.", True),
    ("Доступ ограничен непосредственными подчиненными.", True),
    ("Деректер тек тікелей бағынысты қызметкерлерге қатысты.", True),
    ("Руководитель видит данные своей команды.", False),
    ("Руководитель видит всех сотрудников.", False),
])
def test_visibility_requires_direct_reports_qualifier(answer, expected):
    assert condition_result("base-data-visibility", "direct_reports_only", answer) is expected


@pytest.mark.parametrize("answer,expected", [
    ("Однако кадровый остаток не изменяется.", True),
    ("Официальный остаток не меняется.", True),
    ("Учётный остаток остаётся прежним.", True),
    ("Учетный баланс не увеличивается.", True),
    ("Не изменяется кадровый остаток.", True),
    ("Это не влияет на официальный остаток.", True),
    ("Кадровый остаток увеличивается.", False),
    ("Учетный остаток изменяется.", False),
    ("Кадровый остаток увеличивается, а доступный не меняется.", False),
    ("Кадровый остаток увеличивается. Статус заявки не меняется.", False),
    ("Доступный остаток увеличится после снятия резерва.", False),
])
def test_balance_names_preserve_the_unchanged_official_balance_condition(answer, expected):
    assert condition_result("extra-leave-return", "official_balance_not_double_credited", answer) is expected


@pytest.mark.parametrize("answer,expected", [
    ("Одобренную заявку самостоятельно отменить нельзя.", True),
    ("Если отпуск уже согласован, самостоятельно отменить его нельзя.", True),
    ("Нельзя самому отозвать уже согласованный отпуск.", True),
    ("Отзыв доступен только для заявки на согласовании.", True),
    ("Самостоятельный отзыв возможен лишь до согласования.", True),
    ("Самостоятельно отменить одобренную заявку можно.", False),
    ("Выберите заявку pending и нажмите Отозвать заявку.", False),
    ("Для согласованного отпуска обратитесь в HR.", False),
])
def test_cancellation_requires_explicit_approved_or_pending_boundary(answer, expected):
    assert condition_result("extra-leave-cancel", "approved_not_cancelled_by_author", answer) is expected


@pytest.mark.parametrize("answer,expected", [
    ("Резерв дней освобождается один раз.", True),
    ("После отмены освобождается резерв дней.", True),
    ("Резерв не освобождается.", False),
    ("Дни находятся в резерве.", False),
])
def test_reserve_check_requires_release_not_just_keyword(answer, expected):
    assert condition_result("extra-leave-return", "reserve_released", answer) is expected


@pytest.mark.parametrize("answer,expected", [
    ("Укажите даты. Комментарий необязателен.", True),
    ("Добавьте комментарий при необходимости.", True),
    ("Укажите даты и обязательный комментарий.", False),
    ("Укажите даты и отправьте заявку.", True),
])
def test_comment_is_optional_when_the_answer_mentions_it(answer, expected):
    assert condition_result("base-leave-basic", "comment_is_optional", answer) is expected


def test_hr_word_boundary_is_not_a_literal_backslash():
    assert condition_result("extra-profile-procedure", "contact_hr_for_correction", "Обратитесь в HR.")
    assert not condition_result("extra-profile-procedure", "contact_hr_for_correction", "Обратитесь в WHRONG.")


def test_off_topic_has_no_hr_escalation_but_missing_benefits_policy_does():
    response = {"answer": "Я отвечаю только о PostTech.", "grounded": False,
                "escalation_suggested": False, "mode": "refusal", "sources": [], "actions": []}
    assert evaluate_answer(CASES["base-out-of-domain"], response)["expected_escalation"]
    assert not evaluate_answer(CASES["release-unknown-pet"], response)["expected_escalation"]


def course_retry_checks(answer: str) -> dict:
    return evaluate_answer(CASES["extra-course-retry"], {
        "answer": answer,
        "grounded": True,
        "escalation_suggested": False,
        "mode": "generated",
        "sources": [{"id": "20000000-0000-4000-8000-000000000013"}],
        "actions": [{"id": "academy", "label": "Обучение", "href": "/academy"}],
    })


def test_course_retry_rejects_observed_lost_negation_and_usually_threshold():
    observed = (
        "Если вы не сдали тест курса, курс останется в процессе, и ваша попытка будет сохранена. "
        "Вы можете повторить тест, выбрав в карточке курса опцию «Повторить тест» или «Повторить материал». "
        "Все уроки и материал должны быть завершены до повторной попытки теста. "
        "Проходной балл для курса указан в карточке курса и обычно составляет 80%. "
        "Текущий портал не ограничивает количество неуспешных попыток или требует паузу между ними."
    )
    checks = course_retry_checks(observed)
    assert checks["forbidden:retry_pause_negation_lost"] is False
    assert checks["forbidden:threshold_80_is_not_usually"] is False
    assert checks["condition:threshold_80_is_default"] is False


def test_course_retry_accepts_exact_published_policy():
    knowledge = json.loads((ROOT / "knowledge_base/demo/articles.json").read_text(encoding="utf-8"))
    article = next(row for row in knowledge["articles"] if row["id"] == "20000000-0000-4000-8000-000000000013")
    assert all(course_retry_checks(article["content"]).values())


@pytest.mark.parametrize("phrase", [
    "Портал не ограничивает число попыток и не требует паузу между ними.",
    "Портал не ограничивает число попыток или не требует паузу между ними.",
    "Портал не требует обязательную паузу между попытками.",
])
def test_course_retry_pause_check_does_not_reject_explicit_negation(phrase):
    checks = course_retry_checks("Вы можете повторить тест. " + phrase)
    assert checks["forbidden:retry_pause_negation_lost"] is True


def test_course_threshold_requires_default_label_only_when_numeric_default_is_mentioned():
    assert all(course_retry_checks("Повторите тест. Проходной балл указан в карточке курса и настраивается отдельно.").values())
    assert all(course_retry_checks("Повторите тест. Проходной балл настраивается отдельно; по умолчанию это 80%.").values())
    assert not course_retry_checks("Повторите тест. Проходной балл всегда составляет 80%.")["condition:threshold_80_is_default"]
