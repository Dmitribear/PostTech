import pytest

from app.services.jana_text import normalize_question


@pytest.mark.parametrize("question,expected", [
    ("Как офрмить отпск?", "Как оформить отпуск?"),
    ("Где читать уведмления?", "Где читать уведомления?"),
    ("Как запросить авнас?", "Как запросить аванс?"),
    ("Где УВЕДМЛЕНИЯ?", "Где УВЕДОМЛЕНИЯ?"),
])
def test_only_clear_domain_typos_are_repaired(question, expected):
    assert normalize_question(question) == expected


@pytest.mark.parametrize("question", [
    "Кто назначает облучение?", "Что означает кедровый?",
    "Как исправить заявк?",  # Multiple possible case endings.
    "Как офрмить отпск и проверить уведмления?",  # Too many repairs.
    "Мой номер REQ-отпск-1234_A",  # A token in an ID must not be invented.
    "Как запросить авант?", "Что такое опуск?", "Расскажи про компанию Авант",
    "Открой https://уведмления.ru/отпск", "Напиши на уведмления@example.test",
])
def test_ambiguous_or_unrelated_text_is_not_rewritten(question):
    assert normalize_question(question) == question


def test_correction_preserves_negation_numbers_and_unsupported_conditions():
    assert normalize_question("Отпск ещё не одобрен, сумма 5000 KZT, без согласования.") == (
        "Отпуск ещё не одобрен, сумма 5000 KZT, без согласования.")
