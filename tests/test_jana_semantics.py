import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.domain.knowledge.jana_errors import JanaUnavailable
from app.infrastructure.ai import jana


ARTICLES = [
    {
        "id": str(UUID(int=201)),
        "title": "Заявка на отпуск",
        "source_title": "PostTech: отпуск",
        "content": "Для отпуска укажите даты, комментарий необязателен. Заявка поступит руководителю на согласование.",
        "keywords": ["отпуск"],
    },
    {
        "id": str(UUID(int=202)),
        "title": "Назначенное обучение",
        "source_title": "PostTech: обучение",
        "content": "Откройте раздел «Обучение», выберите назначенный курс, изучите все уроки и пройдите итоговый тест.",
        "keywords": ["обучение", "курс"],
    },
    {
        "id": str(UUID(int=203)),
        "title": "Видимость кадровых данных",
        "source_title": "PostTech: доступ",
        "content": "Сотрудник видит свои сведения. Руководитель видит данные только прямых подчинённых. Делегирование заявки не даёт доступа к полному профилю.",
        "keywords": ["доступ"],
    },
    {
        "id": str(UUID(int=204)),
        "title": "Исправление профиля",
        "source_title": "PostTech: профиль",
        "content": "Профиль доступен только для просмотра. Для исправления телефона или других данных обратитесь в HR; самостоятельного редактирования нет.",
        "keywords": ["профиль", "телефон"],
    },
]


class KnowledgeStore:
    def __init__(self):
        self.rows = deepcopy(ARTICLES)
        self.tables_read = []
        for row in self.rows:
            row.update(
                active=True,
                source_url=None,
                updated_at=datetime.now(timezone.utc).isoformat(),
                reviewed_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                review_due_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                version="3",
            )

    def table(self, table):
        self.tables_read.append(table)
        assert table == "knowledge_articles", "Semantic retrieval must not read personnel tables"
        store = self

        class Query:
            def select(self, columns):
                return self

            def eq(self, key, value):
                assert (key, value) == ("active", True)
                return self

            def limit(self, count):
                assert count >= len(store.rows)
                return self

            def execute(self):
                return SimpleNamespace(data=store.rows)

        return Query()


@pytest.fixture
def knowledge(monkeypatch):
    database = KnowledgeStore()
    settings = SimpleNamespace(
        openai_api_key=SecretStr("synthetic-key-never-sent"),
        openai_model="test-model",
        jana_model_timeout_seconds=20,
    )
    monkeypatch.setattr(jana, "get_supabase_client", lambda: database)
    monkeypatch.setattr(jana, "get_settings", lambda: settings)
    monkeypatch.setattr(jana, "classify_scope", lambda *args, **kwargs: {"intent": "information", "actions": []}, raising=False)
    return database


def generated(answer, indexes=(0,), actions=("leave_new",)):
    return {
        "supported": True,
        "reason": "supported",
        "answer": answer,
        "excerpts": [
            {"source_index": index, "quote": ARTICLES[index]["content"]}
            for index in indexes
        ],
        "actions": list(actions),
    }


def mock_model(monkeypatch, initial, correction=None, verified=True):
    calls = []
    closed = []

    def complete(**kwargs):
        calls.append(kwargs)
        payload = initial if len(calls) == 1 else {
            "supported": verified,
            "answer": (correction if correction is not None else initial.get("answer", "")) if verified else "",
        }
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False), refusal=None),
        )])

    monkeypatch.setattr(jana, "OpenAI", lambda **_: SimpleNamespace(
        close=lambda: closed.append(True),
        chat=SimpleNamespace(completions=SimpleNamespace(create=complete)),
    ))
    return calls, closed


@pytest.mark.parametrize("question,language", [
    ("Нужна пауза в работе на несколько недель — с чего начинать?", "ru"),
    ("Демалысқа өтінішті қалай беремін?", "kk"),
])
def test_semantic_search_receives_all_sources_without_lexical_gate(knowledge, monkeypatch, question, language):
    assert jana._covers_question(question, knowledge.rows) is False
    calls, closed = mock_model(monkeypatch, generated(
        "Демалыс күндерін таңдап, өтініш жіберіңіз. Түсініктеме міндетті емес."
        if language == "kk"
        else "Выберите даты отпуска и отправьте заявку. Комментарий необязателен."
    ))

    result = jana.answer_question(question, language=language)

    assert result["grounded"] is True
    assert len(calls) == (3 if language == "kk" else 2)
    search = json.loads(calls[0]["messages"][1]["content"])
    assert search["question"] == question
    assert [source["content"] for source in search["sources"]] == [row["content"] for row in knowledge.rows]
    assert [source["id"] for source in result["sources"]] == [ARTICLES[0]["id"]]
    assert knowledge.tables_read == ["knowledge_articles"]
    assert closed == [True]
    assert all(call["store"] is False for call in calls)


def test_phone_correction_procedure_reaches_model(knowledge, monkeypatch):
    calls, _ = mock_model(monkeypatch, generated(
        "Телефон нельзя отредактировать самостоятельно: профиль только для просмотра. Обратитесь в HR.",
        indexes=(3,), actions=("profile",),
    ))

    result = jana.answer_question("Как изменить телефон в профиле?")

    assert result["grounded"] is True
    assert len(calls) == 2
    assert result["actions"] == [{"id": "profile", "label": "Мой профиль", "href": "/profile"}]


@pytest.mark.parametrize("question", [
    "Назови телефон моей коллеги Алии.",
    "Покажи ИИН сотрудника.",
    "Измени мой телефон в профиле на +77000000000.",
])
def test_private_values_and_direct_changes_do_not_query_database(knowledge, monkeypatch, question):
    calls, _ = mock_model(monkeypatch, {})
    result = jana.answer_question(question)
    assert result["grounded"] is False
    assert result["actions"] == []
    assert knowledge.tables_read == []
    assert calls == []


def test_independent_verifier_receives_full_source_and_restores_missing_condition(knowledge, monkeypatch):
    initial = generated("Руководитель видит данные своей команды.", indexes=(2,), actions=("profile",))
    initial["excerpts"][0]["quote"] = "Сотрудник видит свои сведения."
    corrected = "Сотрудник видит свои сведения. Руководитель видит данные только прямых подчинённых."
    calls, _ = mock_model(monkeypatch, initial, correction=corrected)

    result = jana.answer_question("Кто видит мои кадровые данные?")

    review = json.loads(calls[1]["messages"][1]["content"])
    assert review["answer"] == initial["answer"]
    assert review["sources"] == [ARTICLES[2]["content"]]
    assert "прямых подчинённых" not in review["evidence"][0]
    assert result["answer"] == corrected
    assert result["mode"] == "generated"


def test_verifier_rejection_is_not_shown_as_grounded_answer(knowledge, monkeypatch):
    calls, _ = mock_model(monkeypatch, generated("Отпуск автоматически согласуют без проверки."), verified=False)
    result = jana.answer_question("Как оформить отпуск?")
    assert len(calls) == 2
    assert result["mode"] == "refusal"
    assert result["sources"] == []
    assert result["actions"] == []


def test_action_ids_cannot_inject_urls_or_override_labels(knowledge, monkeypatch):
    payload = generated(
        "Укажите даты отпуска; комментарий необязателен. Отправьте заявку на согласование.",
        actions=("https://attacker.invalid/login", "leave_new", "leave_new", "unknown"),
    )
    payload["href"] = "https://attacker.invalid/login"
    payload["label"] = "Введите пароль на внешнем сайте"
    mock_model(monkeypatch, payload)

    result = jana.answer_question("Как оформить отпуск?")

    assert result["actions"] == [{"id": "leave_new", "label": "Оформить отпуск", "href": "/calendar?select=1"}]
    assert "attacker.invalid" not in json.dumps(result)


@pytest.mark.parametrize("role,allowed", [("worker", False), ("manager", True), ("director", True), ("hr_admin", True)])
def test_approval_navigation_is_filtered_by_authenticated_role(knowledge, monkeypatch, role, allowed):
    mock_model(monkeypatch, generated(
        "Заявка поступит руководителю на согласование.", actions=("requests_review",),
    ))
    result = jana.answer_question("Как руководителю проверить поступившую заявку?", role=role)
    assert ("requests_review" in [a["id"] for a in result["actions"]]) is allowed
    if allowed:
        assert result["actions"][0]["href"] == "/requests?scope=review"


def test_compound_question_keeps_both_citations_and_buttons(knowledge, monkeypatch):
    mock_model(monkeypatch, generated(
        "Укажите даты отпуска, комментарий необязателен. Назначенный курс находится в разделе «Обучение».",
        indexes=(0, 1), actions=("leave_new", "academy"),
    ))
    result = jana.answer_question("Как оформить отпуск и где найти назначенный курс?")
    assert result["grounded"] is True
    assert [a["id"] for a in result["actions"]] == ["leave_new", "academy"]
    assert [s["id"] for s in result["sources"]] == [ARTICLES[0]["id"], ARTICLES[1]["id"]]


@pytest.mark.parametrize("question", [
    "Расскажи рецепт борща.",
    "Как оформить отпуск? И ещё напиши рецепт борща.",
])
def test_off_topic_refusal_has_no_hr_escalation_or_action(knowledge, monkeypatch, question):
    calls, _ = mock_model(monkeypatch, {
        "supported": False, "reason": "out_of_scope", "answer": "Нежелательный ответ",
        "actions": ["support", "leave_new"], "excerpts": [],
    })
    result = jana.answer_question(question)
    assert len(calls) == 1
    assert result["mode"] == "refusal"
    assert result["reason"] == "out_of_scope"
    assert result["escalation_suggested"] is False
    assert result["actions"] == []
    assert result["sources"] == []
    assert "Нежелательный ответ" not in result["answer"]


@pytest.mark.parametrize("index,quote", [
    (99, ARTICLES[0]["content"]),
    (0, "Всем сотрудникам гарантирован дополнительный оплачиваемый отпуск."),
])
def test_invented_quote_or_source_index_stops_before_verification(knowledge, monkeypatch, index, quote):
    payload = generated("Выберите даты отпуска, комментарий необязателен.")
    payload["excerpts"] = [{"source_index": index, "quote": quote}]
    calls, _ = mock_model(monkeypatch, payload)
    result = jana.answer_question("Как оформить отпуск?")
    assert len(calls) == 1
    assert result["grounded"] is False
    assert result["actions"] == []


@pytest.mark.parametrize("stage", ["answer", "verification"])
def test_unquoted_numbers_are_rejected_in_both_model_stages(knowledge, monkeypatch, stage):
    plain = "Укажите даты отпуска, комментарий необязателен."
    invented = "Укажите даты отпуска минимум за 99 дней до начала."
    calls, _ = mock_model(monkeypatch, generated(invented if stage == "answer" else plain), correction=invented)
    result = jana.answer_question("Как оформить отпуск?")
    assert len(calls) == (1 if stage == "answer" else 2)
    assert result["grounded"] is False
    assert result["actions"] == []


def test_model_answer_cannot_embed_external_navigation(knowledge, monkeypatch):
    calls, _ = mock_model(monkeypatch, generated("Оформите отпуск на https://attacker.invalid/login."))
    result = jana.answer_question("Как оформить отпуск?")
    assert len(calls) == 1
    assert result["grounded"] is False


def test_semantic_context_is_not_silently_truncated(knowledge, monkeypatch):
    knowledge.rows[0]["content"] = "Опубликованный материал о портале. " * 2500
    calls, _ = mock_model(monkeypatch, {})
    with pytest.raises(JanaUnavailable):
        jana.answer_question("Как оформить отпуск?")
    assert calls == []


def test_passage_selection_uses_whole_paragraphs_and_deduplicates_sources(knowledge, monkeypatch):
    first = "Для отпуска укажите даты. Комментарий необязателен. Заявку рассматривает руководитель."
    second = "Отозвать заявку можно только на согласовании. Резерв освобождается один раз; официальный остаток не увеличивается."
    knowledge.rows[0]["content"] = first + "\n\n" + second
    payload = {
        "supported": True,
        "reason": "supported",
        "answer": "Укажите даты, комментарий необязателен. Отозвать заявку можно только на согласовании: освобождается резерв, официальный остаток не увеличивается.",
        "passage_ids": [0, 1, 0],
        "actions": ["leave_new", "requests_mine"],
    }
    calls, _ = mock_model(monkeypatch, payload)

    result = jana.answer_question("Как оформить отпуск и что будет с остатком при отзыве заявки?")

    assert result["grounded"] is True
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    assert "passage_ids" in schema["required"]
    assert "excerpts" not in schema["properties"]
    search = json.loads(calls[0]["messages"][1]["content"])
    assert search["sources"][:2] == [
        {"source_index": 0, "content": first},
        {"source_index": 1, "content": second},
    ]
    review = json.loads(calls[1]["messages"][1]["content"])
    assert review["evidence"] == [
        ARTICLES[0]["source_title"] + ": " + first,
        ARTICLES[0]["source_title"] + ": " + second,
    ]
    assert review["sources"] == [first + "\n\n" + second]
    assert [source["id"] for source in result["sources"]] == [ARTICLES[0]["id"]]
    assert [action["id"] for action in result["actions"]] == ["leave_new", "requests_mine"]


@pytest.mark.parametrize("passage_ids", [
    [], [True], [False], [-1], [4], [0.0], ["0"], [None], [0] * 7, None, "0",
])
def test_invalid_passage_ids_cannot_use_legacy_quote_fallback(knowledge, monkeypatch, passage_ids):
    payload = generated("Укажите даты отпуска, комментарий необязателен.")
    payload["passage_ids"] = passage_ids
    calls, _ = mock_model(monkeypatch, payload)

    result = jana.answer_question("Как оформить отпуск?")

    assert len(calls) == 1
    assert result["grounded"] is False
    assert result["sources"] == []
    assert result["actions"] == []


def test_passage_selection_preserves_conditions_in_verifier_correction(knowledge, monkeypatch):
    payload = {
        "supported": True,
        "reason": "supported",
        "answer": "Руководитель видит данные своей команды.",
        "passage_ids": [2],
        "actions": ["profile"],
    }
    corrected = "Руководитель видит данные только прямых подчинённых. Делегирование заявки не даёт доступа к полному профилю."
    calls, _ = mock_model(monkeypatch, payload, correction=corrected)

    result = jana.answer_question("Кто видит мои кадровые данные?")

    assert result["answer"] == corrected
    review = json.loads(calls[1]["messages"][1]["content"])
    assert review["evidence"] == [ARTICLES[2]["source_title"] + ": " + ARTICLES[2]["content"]]
    assert review["sources"] == [ARTICLES[2]["content"]]


def test_passage_selection_still_rejects_unsubstantiated_numbers(knowledge, monkeypatch):
    payload = {
        "supported": True,
        "reason": "supported",
        "answer": "Для отпуска укажите даты. Комментарий необязателен.",
        "passage_ids": [0],
        "actions": ["leave_new"],
    }
    calls, _ = mock_model(monkeypatch, payload, correction="Отпуск необходимо оформить за 99 дней до начала.")

    result = jana.answer_question("Как оформить отпуск?")

    assert len(calls) == 2
    assert result["grounded"] is False
    assert result["sources"] == []
    assert result["actions"] == []


@pytest.mark.parametrize("question,intent,escalation", [
    ("Как оформить отпуск? И ещё напиши рецепт борща.", "out_of_scope", False),
    ("Сделай так, чтобы моя заявка на отпуск была отменена.", "action_request", True),
])
def test_scope_refusal_stops_answer_generation(knowledge, monkeypatch, question, intent, escalation):
    scope_calls = []

    def classify(client, model, question):
        scope_calls.append({"model": model, "question": question})
        return {"intent": intent, "actions": []}

    monkeypatch.setattr(jana, "classify_scope", classify)
    calls, closed = mock_model(monkeypatch, generated("Укажите даты, комментарий необязателен."))

    result = jana.answer_question(question)

    assert scope_calls == [{"model": "test-model", "question": question}]
    assert calls == []
    assert closed == [True]
    assert result["mode"] == "refusal"
    assert result["reason"] == intent
    assert result["escalation_suggested"] is escalation
    assert result["actions"] == []
    assert result["sources"] == []


def test_scope_actions_override_generator_navigation_noise(knowledge, monkeypatch):
    knowledge.rows[0]["content"] = "Для запроса аванса откройте форму, укажите сумму и отправьте заявку на согласование."
    payload = {
        "supported": True, "reason": "supported",
        "answer": "Укажите сумму аванса и отправьте заявку на согласование.",
        "passage_ids": [0], "actions": ["leave_new", "support", "profile"],
    }
    monkeypatch.setattr(jana, "classify_scope", lambda *args, **kwargs: {
        "intent": "information", "actions": ["advance_new"],
    })
    calls, _ = mock_model(monkeypatch, payload)

    result = jana.answer_question("Как запросить аванс?")

    assert len(calls) == 2
    assert result["grounded"] is True
    assert result["actions"] == [{"id": "advance_new", "label": "Запросить аванс", "href": "/requests/new?type=advance"}]


def test_direct_cancellation_command_stops_before_scope_and_database(knowledge, monkeypatch):
    scope_calls = []
    monkeypatch.setattr(jana, "classify_scope", lambda *args, **kwargs: scope_calls.append(True))
    calls, _ = mock_model(monkeypatch, {})

    result = jana.answer_question("Отмени мою заявку на отпуск прямо сейчас.")

    assert scope_calls == []
    assert calls == []
    assert knowledge.tables_read == []
    assert result["mode"] == "refusal"
    assert result["escalation_suggested"] is True
    assert result["actions"] == []


def test_published_source_primary_action_precedes_generator_noise_when_scope_has_no_action(knowledge, monkeypatch):
    knowledge.rows[0]["id"] = "20000000-0000-4000-8000-000000000001"
    payload = {
        "supported": True, "reason": "supported",
        "answer": "Укажите даты отпуска, комментарий необязателен.",
        "passage_ids": [0], "actions": ["support", "profile"],
    }
    mock_model(monkeypatch, payload)

    result = jana.answer_question("Как оформить отпуск?")

    assert result["actions"] == [{"id": "leave_new", "label": "Оформить отпуск", "href": "/calendar?select=1"}]


def test_status_source_corrects_mistaken_profile_scope_action(knowledge, monkeypatch):
    knowledge.rows[0]["id"] = "20000000-0000-4000-8000-000000000004"
    knowledge.rows[0]["content"] = "Статус заявки и комментарий руководителя, если он оставлен, доступны в разделе «Мои заявки»."
    monkeypatch.setattr(jana, "classify_scope", lambda *args, **kwargs: {
        "intent": "information", "actions": ["profile"],
    })
    payload = {
        "supported": True, "reason": "supported",
        "answer": "Проверьте статус в разделе «Мои заявки». Комментарий руководителя показан, если он оставлен.",
        "passage_ids": [0], "actions": ["profile", "support"],
    }
    mock_model(monkeypatch, payload)

    result = jana.answer_question("Где посмотреть комментарий начальника?")

    assert result["grounded"] is True
    assert result["actions"] == [{"id": "requests_mine", "label": "Мои заявки", "href": "/requests"}]


@pytest.mark.parametrize("question,answer", [
    ("За сколько дней надо подать заявку на отпуск?", "Срок подачи заявки на отпуск в материалах не установлен."),
    ("Когда выплачивается аванс?", "График выплаты аванса не определён в опубликованных материалах."),
    ("Компания оплачивает ветеринара для домашних животных сотрудников?", "Нет информации о такой компенсации в опубликованных правилах."),
])
def test_missing_policy_answer_is_refused_without_navigation(knowledge, monkeypatch, question, answer):
    knowledge.rows[0]["content"] = answer
    payload = {"supported": True, "reason": "supported", "answer": answer,
               "passage_ids": [0], "actions": ["leave_new"]}
    calls, _ = mock_model(monkeypatch, payload)

    result = jana.answer_question(question)

    assert len(calls) == 2
    assert result["mode"] == "refusal"
    assert result["reason"] == "missing_information"
    assert result["grounded"] is False
    assert result["escalation_suggested"] is True
    assert result["actions"] == []
    assert result["sources"] == []


def test_documented_unavailable_operation_is_still_a_supported_procedure(knowledge, monkeypatch):
    answer = "Самостоятельное редактирование телефона не предусмотрено. Для исправления обратитесь в HR."
    knowledge.rows[3]["content"] = answer
    payload = {"supported": True, "reason": "supported", "answer": answer,
               "passage_ids": [3], "actions": ["profile"]}
    mock_model(monkeypatch, payload)

    result = jana.answer_question("Как исправить телефон в профиле?")

    assert result["grounded"] is True
    assert result["actions"][0]["id"] == "profile"


@pytest.mark.parametrize("translation,finish_reason,provider_refusal,expected_supported", [
    ({"supported": True, "answer": "Демалыс күндерін таңдап, өтініш жіберіңіз. Түсініктеме міндетті емес."}, "stop", None, True),
    ({"supported": False, "answer": "Демалыс күндерін таңдап, өтініш жіберіңіз. Түсініктеме міндетті емес."}, "stop", None, False),
    ({"supported": True, "answer": "Демалыс күндерін таңдап, өтініш жіберіңіз. Түсініктеме міндетті емес."}, "length", None, False),
    ({"supported": True, "answer": "Демалыс күндерін таңдап, өтініш жіберіңіз. Түсініктеме міндетті емес."}, "stop", "Cannot translate", False),
    ({"answer": "Демалыс күндерін таңдап, өтініш жіберіңіз. Түсініктеме міндетті емес."}, "stop", None, False),
    ({"supported": True, "answer": "Выберите даты отпуска и отправьте заявку. Комментарий необязателен."}, "stop", None, False),
    ({"supported": True, "answer": "Демалысқа 99 күн бұрын өтініш жіберіңіз."}, "stop", None, False),
])
def test_kazakh_translation_fallback_requires_complete_supported_response(
    knowledge, monkeypatch, translation, finish_reason, provider_refusal, expected_supported
):
    russian = "Выберите даты отпуска и отправьте заявку. Комментарий необязателен."
    initial = {"supported": True, "reason": "supported", "answer": russian,
               "passage_ids": [0], "actions": ["leave_new"]}
    replies = [initial, {"supported": True, "answer": russian}, translation]
    calls, closed = [], []

    def complete(**kwargs):
        calls.append(kwargs)
        is_translation = len(calls) == 3
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish_reason if is_translation else "stop",
            message=SimpleNamespace(
                content=json.dumps(replies[len(calls) - 1], ensure_ascii=False),
                refusal=provider_refusal if is_translation else None,
            ),
        )])

    monkeypatch.setattr(jana, "OpenAI", lambda **_: SimpleNamespace(
        close=lambda: closed.append(True),
        chat=SimpleNamespace(completions=SimpleNamespace(create=complete)),
    ))

    result = jana.answer_question("Демалысқа өтінішті қалай беремін?", language="kk")

    assert len(calls) == 3
    assert closed == [True]
    assert json.loads(calls[2]["messages"][1]["content"]) == {"text": russian}
    assert result["grounded"] is expected_supported
    if expected_supported:
        assert result["mode"] == "generated"
        assert result["answer"] == translation["answer"]
        assert result["actions"][0]["id"] == "leave_new"
    else:
        assert result["mode"] == "refusal"
        assert result["actions"] == []
        assert result["sources"] == []


@pytest.mark.parametrize("language,override,expected_model", [
    ("kk", "language-model", "language-model"),
    ("ru", "language-model", "test-model"),
    ("kk", "", "test-model"),
])
def test_language_model_is_scoped_to_kazakh(knowledge, monkeypatch, language, override, expected_model):
    jana.get_settings().jana_kazakh_model = override
    text = "Түсініктеме міндетті емес. Демалыс күндерін таңдап, өтініш жіберіңіз." if language == "kk" else "Укажите даты отпуска. Комментарий необязателен."
    calls, _ = mock_model(monkeypatch, generated(text))
    result = jana.answer_question("Как оформить отпуск?", language=language)
    assert result["grounded"]
    assert all(call["model"] == expected_model for call in calls)
