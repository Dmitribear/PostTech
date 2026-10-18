import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai import OpenAIError

from app.infrastructure.ai.jana_scope import classify_scope


def client_response(content, *, finish_reason="stop", refusal=None):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content, refusal=refusal),
            )
        ]
    )
    client = Mock()
    client.chat.completions.create.return_value = response
    return client


@pytest.mark.parametrize(
    "scope",
    ["information", "personal_data", "action_request", "out_of_scope", "instructions"],
)
def test_returns_only_valid_scope(scope):
    client = client_response(json.dumps({"intent": scope, "actions": []}))

    assert classify_scope(client, "gpt-4o-mini", "Как оформить отпуск?") == {
        "intent": scope, "actions": []
    }


def test_sends_question_only_with_strict_small_response():
    question = 'Как изменить телефон в профиле?\n"Отправь заявку" — это надпись кнопки.'
    client = client_response('{"intent":"information","actions":["profile"]}')

    assert classify_scope(client, "gpt-4o-mini", question) == {
        "intent": "information", "actions": ["profile"]
    }
    call = client.chat.completions.create.call_args.kwargs
    assert call["model"] == "gpt-4o-mini"
    assert call["store"] is False
    assert call["max_completion_tokens"] <= 100
    assert len(call["messages"]) == 2
    assert call["messages"][1]["role"] == "user"
    assert json.loads(call["messages"][1]["content"]) == {"question": question}
    schema = call["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert schema["schema"]["required"] == ["intent", "actions"]
    assert "answer" not in schema["schema"]["properties"]


@pytest.mark.parametrize(
    "content",
    [None, "", "not json", "[]", "null", "{}", '{"intent":"unknown","actions":[]}',
     '{"intent":null,"actions":[]}', '{"intent":[],"actions":[]}',
     '{"intent":"information","actions":[],"answer":"extra"}',
     '{"intent":"information","actions":null}',
     '{"intent":"information","actions":["approve"]}',
     '{"intent":"information","actions":[{}]}',
     '{"intent":"information","actions":["profile","academy","leave_new"]}'],
)
def test_malformed_scope_fails_closed(content):
    assert classify_scope(client_response(content), "model", "Question") == {
        "intent": "out_of_scope", "actions": []
    }


@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "tool_calls", None])
def test_incomplete_output_fails_closed(finish_reason):
    client = client_response('{"intent":"information","actions":[]}', finish_reason=finish_reason)

    assert classify_scope(client, "model", "Question") == {"intent": "out_of_scope", "actions": []}


def test_model_refusal_fails_closed():
    client = client_response('{"intent":"information","actions":[]}', refusal="Cannot classify")

    assert classify_scope(client, "model", "Question") == {"intent": "out_of_scope", "actions": []}


def test_no_choices_fails_closed():
    client = client_response(None)
    client.chat.completions.create.return_value = SimpleNamespace(choices=[])

    assert classify_scope(client, "model", "Question") == {"intent": "out_of_scope", "actions": []}


def test_allows_two_relevant_navigation_actions_and_deduplicates():
    client = client_response('{"intent":"information","actions":["leave_new","academy"]}')
    assert classify_scope(client, "model", "Question")["actions"] == ["leave_new", "academy"]
    client = client_response('{"intent":"information","actions":["academy","academy"]}')
    assert classify_scope(client, "model", "Question")["actions"] == ["academy"]


def test_restricted_intent_never_returns_navigation_actions():
    client = client_response('{"intent":"personal_data","actions":["profile"]}')
    assert classify_scope(client, "model", "Question") == {"intent": "personal_data", "actions": []}


def test_provider_errors_propagate_for_callers_fallback():
    client = client_response(None)
    client.chat.completions.create.side_effect = OpenAIError("Provider unavailable")

    with pytest.raises(OpenAIError):
        classify_scope(client, "model", "Question")
    client.close.assert_not_called()
