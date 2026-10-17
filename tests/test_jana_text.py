import pytest

from app.domain.knowledge.jana_text import normalize_question


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Как офрмить отпск?", "Как оформить отпуск?"),
        ("Где читать уведмления?", "Где читать уведомления?"),
        ("Как запросить авнас?", "Как запросить аванс?"),
        ("Где УВЕДМЛЕНИЯ?", "Где УВЕДОМЛЕНИЯ?"),
        ("Для заявки на авнс нужна сумма?", "Для заявки на аванс нужна сумма?"),
        ("Как запросить АВНС?", "Как запросить АВАНС?"),
        ("Сведения в профеле доступны мне?", "Сведения в профиле доступны мне?"),
        ("Материал назначеного курса", "Материал назначенного курса"),
        ("Курс есть в катологе.", "Курс есть в каталоге."),
        (
            "Руковадитель видит прямых подчинёных?",
            "Руководитель видит прямых подчинённых?",
        ),
        ("Где появляются уведомленья?", "Где появляются уведомления?"),
        ("Где написан комент к заявке?", "Где написан комментарий к заявке?"),
        ("За сколко дней подавать заявку?", "За сколько дней подавать заявку?"),
    ],
)
def test_only_clear_domain_typos_are_repaired(question, expected):
    assert normalize_question(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Кто назначает облучение?",
        "Что означает кедровый?",
        "Как исправить заявк?",  # Multiple possible case endings.
        "Как офрмить отпск и проверить уведмления?",  # Too many repairs.
        "Мой номер REQ-отпск-1234_A",  # A token in an ID must not be invented.
        "Как запросить авант?",
        "Что такое опуск?",
        "Расскажи про компанию Авант",
        "Открой https://уведмления.ru/отпск",
        "Напиши на уведмления@example.test",
        "Что такое авнт?",
        "Что означает авн?",
        "Сравни слово авнсс с авансом.",
        "Сотрудник Фаил и компания Авант",  # Real names are not domain misspellings.
        "Кто видит REQ-авнс-02 и HR_профеле_15?",
        "Открой https://example.test/авнс?поле=профеле и www.example.test/катологе",
        "Напиши на авнс@example.test или профеле@example.test",
        "В профеле есть авнс и комент.",  # Three reviewed repairs still fail closed.
    ],
)
def test_ambiguous_or_unrelated_text_is_not_rewritten(question):
    assert normalize_question(question) == question


def test_correction_preserves_negation_numbers_and_unsupported_conditions():
    assert normalize_question(
        "Отпск ещё не одобрен, сумма 5000 KZT, без согласования."
    ) == ("Отпуск ещё не одобрен, сумма 5000 KZT, без согласования.")


def test_reviewed_short_typos_preserve_negations_numbers_and_unknown_terms():
    assert normalize_question(
        "Не менять сумму -5000.50: авнс в профеле, без согласования, авнт."
    ) == ("Не менять сумму -5000.50: аванс в профиле, без согласования, авнт.")


def test_address_and_identifier_tokens_do_not_consume_the_repair_budget():
    assert normalize_question(
        "https://example.test/авнс HR_профеле_15: авнс в профеле."
    ) == ("https://example.test/авнс HR_профеле_15: аванс в профиле.")
