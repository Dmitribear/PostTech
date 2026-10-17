"""Evidence integrity is independent of Jana's wording/model quality."""

import json

import pytest

from app.services.jana_errors import JanaUnavailable
from app.services.jana_evidence import MAX_ARTICLES, prepare_evidence, select_excerpts


def article(number=1, content="Первое правило. Исключение: только после проверки."):
    return {"id": f"40000000-0000-4000-8000-{number:012d}", "title": "Новое правило",
            "source_title": "Опубликованная инструкция", "content": content, "active": True}


def test_new_article_is_included_without_any_faq_entry_or_question_example():
    row = article(content="Синие контейнеры принимают в северном пункте. Забор до 15:30.")
    bundle = prepare_evidence([row])
    assert len(bundle.documents) == 1
    assert all(span.text in row["content"] for span in bundle.spans)
    assert "Синие контейнеры" in bundle.prompt_text
    assert "15:30" in bundle.prompt_text
    sources = select_excerpts(bundle, [span.id for span in bundle.spans])
    assert sources == [{"id": row["id"], "title": row["source_title"],
                        "url": f"/api/v1/ai/sources/{row['id']}", "excerpt": row["content"]}]


def test_entire_source_and_qualifying_context_reach_the_reader():
    text = '  Отпуск разрешён. Но только после проверки; раньше нельзя.\n\nКомментарий без точки  '
    bundle = prepare_evidence([article(content=text)])
    doc = bundle.documents[0]
    assert doc.content == text
    assert "".join(span.text for span in doc.spans).replace(" ", "") == text.strip().replace(" ", "").replace("\n", "")
    assert doc.spans[1].text == "Но только после проверки; раньше нельзя."
    assert select_excerpts(bundle, [doc.spans[0].id, doc.spans[-1].id])[0]["excerpt"] == text.strip()


def test_internal_dots_decimals_and_newlines_preserve_every_source_character():
    text = 'Файл .ics доступен при сумме 1.5. «Готово?»\nДа.\n\nБез точки'
    bundle = prepare_evidence([article(content=text)])
    for span in bundle.spans:
        assert span.text == text[span.start:span.end]
    covered = {i for span in bundle.spans for i in range(span.start, span.end)}
    assert all(character.isspace() or index in covered for index, character in enumerate(text))
    assert ".ics" in bundle.spans[0].text and "1.5" in bundle.spans[0].text


def test_ids_and_prompt_are_independent_of_database_row_order():
    a, b = article(1), article(2, "Другой источник.")
    first, second = prepare_evidence([a, b]), prepare_evidence([b, a])
    assert first.spans == second.spans
    assert first.prompt_text == second.prompt_text


def test_edit_outside_selected_quote_invalidates_all_old_ids():
    old = prepare_evidence([article()])
    new = prepare_evidence([article(content=article()["content"] + " Новое ограничение.")])
    assert old.spans[0].text == new.spans[0].text
    assert not set(old.by_id).intersection(new.by_id)
    with pytest.raises(ValueError, match="stale"):
        select_excerpts(new, [old.spans[0].id])


def test_deactivation_removes_article_and_old_selections():
    row = article()
    old = prepare_evidence([row])
    new = prepare_evidence([{**row, "active": False}])
    assert new.documents == new.spans == ()
    with pytest.raises(ValueError, match="stale"):
        select_excerpts(new, [old.spans[0].id])


def test_database_projection_without_active_column_is_supported():
    row = article()
    del row["active"]
    assert len(prepare_evidence([row]).documents) == 1


@pytest.mark.parametrize("change", [{"id": "invalid"}, {"content": " "},
                                   {"content": None}, {"source_title": ""},
                                   {"title": "x" * 501}, {"active": "true"},
                                   {"active": None}, {"content": "NUL\x00"}])
def test_malformed_active_sources_fail_explicitly(change):
    with pytest.raises(JanaUnavailable):
        prepare_evidence([{**article(), **change}])


def test_duplicate_sources_are_not_arbitrarily_chosen():
    row = article()
    with pytest.raises(JanaUnavailable, match="duplicate"):
        prepare_evidence([row, {**row, "content": "Иное правило."}])


def test_article_and_prompt_budgets_never_silently_drop_sources():
    with pytest.raises(JanaUnavailable, match="article limit"):
        prepare_evidence([article(i) for i in range(MAX_ARTICLES + 1)])
    with pytest.raises(JanaUnavailable, match="text limit"):
        prepare_evidence([article(content="x" * 20_001)])
    with pytest.raises(JanaUnavailable, match="evidence budget"):
        prepare_evidence([article()], max_total_chars=10)
    with pytest.raises(JanaUnavailable, match="prompt budget"):
        prepare_evidence([article()], max_prompt_chars=10)


def test_model_does_not_receive_examples_external_urls_or_private_extra_fields():
    row = {**article(), "source_url": "https://untrusted.example/", "keywords": ["key"],
           "demo_questions": ["DONOTINDEX"], "private_profile": "SECRET"}
    prompt = prepare_evidence([row]).prompt_text
    assert all(value not in prompt for value in ("https://", "DONOTINDEX", "SECRET", "keywords"))
    assert json.loads(prompt)["articles"][0]["sentences"]


def test_multiple_selections_from_one_source_include_intervening_context_once():
    bundle = prepare_evidence([article(content="Обычно можно. Но требуется разрешение HR. Потом отправьте заявку.")])
    sources = select_excerpts(bundle, [bundle.spans[0].id, bundle.spans[2].id])
    assert len(sources) == 1
    assert sources[0]["excerpt"] == bundle.documents[0].content


def test_multiple_articles_keep_selection_order_for_citation_numbers():
    bundle = prepare_evidence([article(1), article(2, "Второе правило.")])
    sources = select_excerpts(bundle, [bundle.documents[1].spans[0].id, bundle.documents[0].spans[0].id])
    assert [source["id"] for source in sources] == [article(2)["id"], article(1)["id"]]


@pytest.mark.parametrize("ids", [[], ["invented"], "Sabc", [None]])
def test_bad_model_selection_is_not_rendered(ids):
    with pytest.raises(ValueError):
        select_excerpts(prepare_evidence([article()]), ids)


def test_repeated_or_over_budget_selection_is_not_silently_repaired():
    bundle = prepare_evidence([article()])
    first = bundle.spans[0].id
    with pytest.raises(ValueError, match="Duplicate"):
        select_excerpts(bundle, [first, first])
    with pytest.raises(ValueError, match="number"):
        select_excerpts(bundle, [span.id for span in bundle.spans], max_spans=1)
    with pytest.raises(ValueError, match="length budget"):
        select_excerpts(bundle, [first], max_chars=2)


def test_snapshot_lookup_cannot_be_mutated():
    bundle = prepare_evidence([article()])
    with pytest.raises(TypeError):
        bundle.by_id["invented"] = bundle.spans[0]
