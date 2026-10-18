import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.infrastructure.ai.jana_conditions import (
    missing_policy_answer,
    retain_leave_conditions,
    retain_portal_terms,
)


ARTICLES = {
    article["id"]: article
    for article in json.loads(
        (Path(__file__).resolve().parents[1] / "knowledge_base/demo/articles.json")
        .read_text(encoding="utf-8")
    )["articles"]
}
CANCELLATION_ID = "20000000-0000-4000-8000-000000000012"
BALANCE_ID = "20000000-0000-4000-8000-000000000005"
LEAVE_ID = "20000000-0000-4000-8000-000000000001"
COURSE_ID = "20000000-0000-4000-8000-000000000008"
RETRY_ID = "20000000-0000-4000-8000-000000000013"


@pytest.mark.parametrize("text", [
    "Проходной балл указан в карточке курса и составляет 80%.",
    "Порог прохождения — 80%.",
])
def test_default_score_does_not_become_a_fixed_threshold(text):
    result = retain_portal_terms(text, [ARTICLES[COURSE_ID]], "ru")
    assert "80% по умолчанию" in result
    assert retain_portal_terms(result, [ARTICLES[COURSE_ID]], "ru") == result


def test_cancellation_adds_missing_restrictions_as_exact_source_sentences():
    answer = "Откройте свою заявку и подтвердите отзыв."
    result = retain_leave_conditions(answer, [ARTICLES[CANCELLATION_ID]], "ru")
    expected_sentences = [
        "Автор может отозвать только свою заявку со статусом «На согласовании» (pending).",
        "Уже согласованный отпуск самостоятельно отменить этой кнопкой нельзя.",
    ]

    assert result == " ".join([answer, *expected_sentences])
    for sentence in expected_sentences:
        assert sentence in ARTICLES[CANCELLATION_ID]["content"]


def test_cancellation_return_explains_unchanged_official_balance():
    answer = "После отзыва резерв освобождается один раз."
    result = retain_leave_conditions(answer, [ARTICLES[CANCELLATION_ID]], "ru")
    sentence = (
        "Доступный остаток увеличивается на освобождённые дни, "
        "а кадровый остаток не меняется."
    )

    assert result.startswith(answer)
    assert sentence in result
    assert sentence in ARTICLES[CANCELLATION_ID]["content"]
    assert result.count(sentence) == 1


def test_balance_uses_its_own_unchanged_official_balance_evidence():
    answer = "При отклонении заявки резерв освобождается."
    result = retain_leave_conditions(answer, [ARTICLES[BALANCE_ID]], "ru")
    sentence = (
        "При отклонении или отзыве ожидающей заявки резерв освобождается один раз, "
        "доступные дни возвращаются, а кадровый остаток не изменяется."
    )

    assert result == answer + " " + sentence
    assert sentence in ARTICLES[BALANCE_ID]["content"]
    assert "Уже согласованный отпуск" not in result


@pytest.mark.parametrize(
    "answer",
    [
        (
            "Можно отозвать только свою заявку на согласовании. "
            "Одобренный отпуск отменить нельзя. Резерв освобождается, "
            "кадровый остаток не меняется."
        ),
        (
            "Отзыв доступен лишь для заявки со статусом pending. "
            "Нельзя отозвать согласованный отпуск. Доступные дни возвращаются, "
            "официальный остаток не изменяется."
        ),
    ],
)
def test_already_explained_conditions_are_not_repeated(answer):
    assert retain_leave_conditions(answer, [ARTICLES[CANCELLATION_ID]], "ru") == answer


def test_does_not_invent_missing_conditions_even_for_known_article_id():
    answer = "В карточке заявки доступна история."
    source = {
        "id": CANCELLATION_ID,
        "content": "История отображается в карточке заявки.",
    }

    assert retain_leave_conditions(answer, [source], "ru") == answer


def test_does_not_copy_unrelated_source_or_invent_conditions_without_sources():
    answer = "После отзыва резерв освобождается."
    unrelated = {**ARTICLES[CANCELLATION_ID], "id": "other-article"}

    assert retain_leave_conditions(answer, [], "ru") == answer
    assert retain_leave_conditions(answer, [unrelated], "ru") == answer


def test_uses_full_selected_article_when_excerpt_omitted_conditions():
    source = {
        "id": CANCELLATION_ID,
        "content": "Статус станет «Отозвана».",
        "full_content": ARTICLES[CANCELLATION_ID]["content"],
    }
    answer = "Откройте свою заявку и подтвердите отзыв."

    assert retain_leave_conditions(answer, [source], "ru") == retain_leave_conditions(
        answer, [ARTICLES[CANCELLATION_ID]], "ru"
    )


def test_does_not_append_balance_condition_to_unrelated_balance_question():
    answer = "Доступные дни показаны в профиле."

    assert retain_leave_conditions(answer, [ARTICLES[BALANCE_ID]], "ru") == answer


def test_preserves_original_answer_and_does_not_mutate_sources():
    answer = "  Откройте заявку.\nПодтвердите отзыв.  "
    sources = [deepcopy(ARTICLES[CANCELLATION_ID])]
    before = deepcopy(sources)

    result = retain_leave_conditions(answer, sources, "ru")

    assert result.startswith(answer + " ")
    assert sources == before
    assert all("status" not in source for source in sources)
    assert "Заявка отозвана мной" not in result


def test_kazakh_answer_is_untouched():
    answer = "Өтінімді тек келісу кезеңінде қайтарып алуға болады."

    assert retain_leave_conditions(answer, [ARTICLES[CANCELLATION_ID]], "kk") == answer


@pytest.mark.parametrize(
    "question",
    ["Как оформить отпуск?", "Как подать заявление на отпуск?", "Хочу взять отпуск, с чего начать?"],
)
def test_creation_does_not_acquire_cancellation_conditions(question):
    answer = "Выберите даты и отправьте заявку. Дни резервируются при отправке."
    sources = [ARTICLES[LEAVE_ID], ARTICLES[CANCELLATION_ID], ARTICLES[BALANCE_ID]]

    assert retain_leave_conditions(answer, sources, "ru", question) == answer


def test_return_answer_keeps_release_trigger_with_official_balance_condition():
    answer = "Доступные дни возвращаются."
    result = retain_leave_conditions(
        answer, [ARTICLES[CANCELLATION_ID]], "ru", "Вернутся ли дни после отмены заявки?"
    )
    conditional_evidence = (
        "При отзыве или отклонении ожидающей заявки её резерв дней освобождается один раз. "
        "Доступный остаток увеличивается на освобождённые дни, а кадровый остаток не меняется."
    )

    assert conditional_evidence in ARTICLES[CANCELLATION_ID]["content"]
    assert conditional_evidence in result
    assert "только свою заявку со статусом «На согласовании»" in result
    assert "Уже согласованный отпуск самостоятельно отменить этой кнопкой нельзя." in result


def test_reversed_unchanged_balance_word_order_is_not_repeated():
    answer = (
        "Отозвать можно только заявку на согласовании. Согласованный отпуск отменить нельзя. "
        "Резерв освобождается, но не изменяется кадровый остаток."
    )

    assert retain_leave_conditions(
        answer, [ARTICLES[CANCELLATION_ID]], "ru", "Вернутся ли дни после отзыва?"
    ) == answer


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Когда выплачивается аванс?", "График выплат аванса не установлен в базе знаний. Обратитесь в HR."),
        ("За сколько дней надо подать заявку на отпуск?", "Срок подачи не определён. Уточните у HR."),
        ("Сколько дней отпуска положено?", "Ежегодная норма дней не утверждена в этой базе."),
        ("Какой размер компенсации за автомобиль?", "Нет подтверждённой информации о компенсации."),
        ("Компания оплачивает лечение питомца?", "Информация об этом правиле отсутствует. В базе нет информации."),
    ],
)
def test_missing_company_policy_requires_refusal(question, answer):
    assert missing_policy_answer(question, answer)


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Как запросить аванс?", "Срок выплаты не установлен. Для подачи укажите сумму и отправьте заявку."),
        ("Как отменить согласованный отпуск?", "Самостоятельная отмена не предусмотрена. Обратитесь в HR."),
        ("Как изменить телефон в профиле?", "Профиль доступен только для чтения; обратитесь в HR."),
        ("Что делать, если не сдал тест?", "Ограничение числа попыток не установлено; повторите тест."),
    ],
)
def test_supported_procedure_or_restriction_is_not_unknown_policy(question, answer):
    assert not missing_policy_answer(question, answer)


def test_known_course_retry_timing_is_not_missing_company_policy():
    assert not missing_policy_answer(
        "Когда можно повторить тест курса?",
        "Обязательная пауза между попытками не установлена. Можно повторить тест.",
    )


def test_overlap_correction_is_about_only_pending_or_approved_requests():
    answer = "Убедитесь, что даты не пересекаются с другими вашими заявками."

    result = retain_portal_terms(answer, [ARTICLES[LEAVE_ID]], "ru")

    assert result == answer + " Проверка пересечения относится к ожидающим или одобренным отпускам."


def test_approval_word_in_another_sentence_does_not_hide_overlap_qualification():
    answer = (
        "После отправки заявка получает статус «На согласовании». "
        "Убедитесь, что даты не пересекаются с другими вашими заявками."
    )

    result = retain_portal_terms(answer, [ARTICLES[LEAVE_ID]], "ru")

    assert result.endswith("Проверка пересечения относится к ожидающим или одобренным отпускам.")


def test_qualified_overlap_sentence_is_not_repeated():
    answer = "Портал проверяет пересечение с вашими ожидающими или одобренными отпусками."

    assert retain_portal_terms(answer, [ARTICLES[LEAVE_ID]], "ru") == answer


def test_course_material_precedes_quiz_but_course_completion_does_not():
    answer = "После завершения курса ответьте на все вопросы теста и нажмите «Завершить тест»."

    result = retain_portal_terms(answer, [ARTICLES[COURSE_ID]], "ru")

    assert result == (
        "После изучения материала и завершения уроков ответьте на все вопросы теста "
        "и нажмите «Завершить тест»."
    )


def test_portal_term_repairs_require_evidence_and_leave_kazakh_untouched():
    answer = "После завершения курса ответьте на вопросы теста."

    assert retain_portal_terms(answer, [], "ru") == answer
    assert retain_portal_terms(answer, [ARTICLES[COURSE_ID]], "kk") == answer


def test_portal_term_repairs_do_not_mutate_sources():
    sources = [deepcopy(ARTICLES[LEAVE_ID]), deepcopy(ARTICLES[COURSE_ID])]
    before = deepcopy(sources)

    retain_portal_terms("Проверьте пересечения. После завершения курса ответьте на вопросы теста.", sources, "ru")

    assert sources == before


def test_retry_replaces_lost_pause_negation_in_actual_generated_answer():
    answer = (
        "Если вы не сдали тест курса, курс останется в процессе, и ваша попытка будет сохранена. "
        "Вы можете повторить тест, выбрав в карточке курса опцию «Повторить тест» или «Повторить материал». "
        "Все уроки и материал должны быть завершены до повторной попытки теста. "
        "Проходной балл для курса указан в карточке курса и обычно составляет 80%. "
        "Текущий портал не ограничивает количество неуспешных попыток или требует паузу между ними."
    )
    evidence = (
        "Текущий портал не задаёт ограничения на число неуспешных попыток "
        "или обязательную паузу между ними."
    )

    result = retain_portal_terms(answer, [ARTICLES[COURSE_ID], ARTICLES[RETRY_ID]], "ru")

    assert result == answer.replace("обычно составляет 80%", "по умолчанию составляет 80%").replace(
        "Текущий портал не ограничивает количество неуспешных попыток или требует паузу между ними.",
        evidence,
    )
    assert evidence in ARTICLES[RETRY_ID]["content"]
    assert "требует паузу" not in result
    assert result.count(evidence) == 1


def test_retry_rule_uses_full_source_and_replaces_instead_of_appending():
    evidence = (
        "Текущий портал не задаёт ограничения на число неуспешных попыток "
        "или обязательную паузу между ними."
    )
    source = {"id": RETRY_ID, "content": "Откройте курс.", "full_content": ARTICLES[RETRY_ID]["content"]}

    result = retain_portal_terms("Между попытками требуется обязательная пауза.", [source], "ru")

    assert result == evidence


def test_retry_rule_does_not_duplicate_when_both_limit_and_pause_are_distorted():
    answer = "Количество попыток ограничено. Между попытками нужна обязательная пауза."
    evidence = (
        "Текущий портал не задаёт ограничения на число неуспешных попыток "
        "или обязательную паузу между ними."
    )

    assert retain_portal_terms(answer, [ARTICLES[RETRY_ID]], "ru") == evidence


@pytest.mark.parametrize(
    "sources",
    [
        [],
        [{"id": RETRY_ID, "content": "Обратитесь в HR для уточнения условий пересдачи."}],
        [{"id": "another-article", "content": ARTICLES[RETRY_ID]["content"]}],
        [ARTICLES[COURSE_ID]],
    ],
)
def test_retry_condition_is_not_invented_without_confirmed_retry_source(sources):
    answer = "Текущий портал не ограничивает количество попыток или требует паузу между ними."

    assert retain_portal_terms(answer, sources, "ru") == answer


def test_default_score_correction_requires_same_confirmed_source_value():
    answer = "Проходной балл обычно составляет 90%."

    assert retain_portal_terms(answer, [ARTICLES[COURSE_ID]], "ru") == answer
    answer = "Проходной балл обычно составляет 80%."
    unknown = {"id": COURSE_ID, "content": "Проходной балл указан в карточке курса."}
    assert retain_portal_terms(answer, [unknown], "ru") == answer


def test_attempt_repair_preserves_material_requirement_and_kazakh():
    answer = "Перед повторной попыткой завершите все уроки и материал."
    assert retain_portal_terms(answer, [ARTICLES[RETRY_ID]], "ru") == answer
    answer = "Между попытками требуется пауза."
    assert retain_portal_terms(answer, [ARTICLES[RETRY_ID]], "kk") == answer
