"""The isolated demo must not return a quote from a changed knowledge snapshot."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services.jana_intent import Decision
from examples import jana_local_demo as demo


@pytest.mark.parametrize("change", ["content", "inactive", "archived", "expired", "unchanged"])
def test_demo_rechecks_source_after_inference(monkeypatch, change):
    now = datetime.now(timezone.utc)
    original_text = "Отпуск оформляется через раздел заявок."
    storage = [{
        "id": "20000000-0000-4000-8000-000000000001", "title": "Отпуск",
        "source_title": "Демо: отпуск", "source_url": None, "content": original_text,
        "active": True, "editorial_state": "published", "version": "1",
        "updated_at": (now - timedelta(days=2)).isoformat(),
        "reviewed_at": (now - timedelta(days=1)).isoformat(),
        "review_due_at": (now + timedelta(days=1)).isoformat(),
    }]
    reads = []

    def read_storage():
        reads.append(True)
        return deepcopy([article for article in storage if demo.usable(article)])

    class Reader:
        def __init__(self, settings):
            pass

        def select(self, question, context):
            # The model has already read the old snapshot when storage changes.
            if change == "content":
                storage[0]["content"] = "Новая редакция правил оформления отпуска."
            elif change == "inactive":
                storage[0]["active"] = False
            elif change == "archived":
                storage[0]["editorial_state"] = "archived"
            elif change == "expired":
                storage[0]["review_due_at"] = (now - timedelta(seconds=1)).isoformat()
            return Decision(understanding="Порядок оформления отпуска", kind="answer",
                            evidence_ids=[context[0]["sentences"][0]["id"]], clarification="none")

    monkeypatch.setattr(demo, "articles", read_storage)
    monkeypatch.setattr(demo, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(demo, "LocalReader", Reader)
    with TestClient(demo.app) as client:
        response = client.post("/api/v1/ai/ask", json={"question": "Как оформить отпуск?"})
    assert len(reads) == 2
    if change == "unchanged":
        assert response.status_code == 200
        assert response.json()["sources"][0]["excerpt"] == original_text
    else:
        assert response.status_code == 503
        assert response.json() == {"detail": "Jana AI is temporarily unavailable"}
        assert original_text not in response.text
