"""Current local reader storage/HTTP contract; historical cloud tests are archived."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext
from app.services import jana
from app.services.jana_intent import Decision
from app.services.jana_errors import JanaUnavailable
from app.services.jana_knowledge import freshness, metadata, snapshot_version, usable

NOW = datetime.now(timezone.utc)
ARTICLE = dict(id=str(UUID(int=101)), active=True, title="Отпуск", source_title="Демо: отпуск",
               content="Окончательное решение принимает HR. Дни списываются один раз.", source_url=None,
               editorial_state="published", version="1", updated_at=NOW.isoformat(),
               reviewed_at=(NOW-timedelta(days=1)).isoformat(), review_due_at=(NOW+timedelta(days=30)).isoformat())

class Query:
    def __init__(self, rows): self.rows=deepcopy(rows)
    def table(self, name):
        assert name == "knowledge_articles", "Personal HR tables must never enter Jana"
        return self
    def select(self, fields): self.fields=fields.split(","); return self
    def eq(self, key, value): self.rows=[r for r in self.rows if r.get(key)==value]; return self
    def order(self, key): self.rows.sort(key=lambda r:r[key]); return self
    def limit(self, count): self.rows=self.rows[:count]; return self
    def execute(self): return SimpleNamespace(data=[{k:r.get(k) for k in self.fields} for r in self.rows])

class Reader:
    def select(self, question, context):
        return Decision(understanding=question,kind="answer",clarification="none",
                        evidence_ids=[context[0]["sentences"][0]["id"]])

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(jana,"get_supabase_client",lambda:Query([ARTICLE]))
    monkeypatch.setattr(jana,"LocalReader",lambda settings:Reader())
    old=app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user]=lambda:UserContext(id=str(UUID(int=5)),auth_user_id=str(UUID(int=6)),role="worker")
    with TestClient(app) as result: yield result
    app.dependency_overrides.clear();app.dependency_overrides.update(old)

@pytest.mark.parametrize("role",["worker","manager","director","hr_admin"])
def test_all_roles_receive_only_public_evidence(client,role):
    app.dependency_overrides[get_current_user]=lambda:UserContext(id=str(UUID(int=5)),auth_user_id=str(UUID(int=6)),role=role)
    response=client.post("/api/v1/ai/ask",json={"question":"Кто принимает окончательное решение?"})
    assert response.status_code==200
    source=response.json()["sources"][0]
    assert source["excerpt"] in ARTICLE["content"]
    assert source["version"]==snapshot_version(ARTICLE)
    original=client.get(source["url"])
    assert original.status_code==200 and original.json()["freshness"]=="reviewed"

@pytest.mark.parametrize("change",[{"active":False},{"editorial_state":"draft"},{"editorial_state":"archived"},
                                  {"reviewed_at":None},{"review_due_at":None},
                                  {"review_due_at":(NOW-timedelta(days=2)).isoformat()},
                                  {"reviewed_at":(NOW+timedelta(days=2)).isoformat()}])
def test_unpublished_or_unverified_articles_cannot_be_answer_sources(client,monkeypatch,change):
    row=ARTICLE|change
    monkeypatch.setattr(jana,"get_supabase_client",lambda:Query([row]))
    assert jana._published_articles()==[]
    assert client.get("/api/v1/ai/sources/"+row["id"]).status_code==404
    result=client.post("/api/v1/ai/ask",json={"question":"Кто согласует отпуск?"})
    assert result.status_code==200 and not result.json()["grounded"]

@pytest.mark.parametrize("field,value",[("content","Новое правило."),("source_title","Другой документ"),("version","2")])
def test_old_source_version_is_rejected_after_edit(client,monkeypatch,field,value):
    version=snapshot_version(ARTICLE)
    monkeypatch.setattr(jana,"get_supabase_client",lambda:Query([ARTICLE|{field:value}]))
    assert client.get(f"/api/v1/ai/sources/{ARTICLE['id']}?version={version}").status_code==409


def test_clarification_does_not_offer_automatic_escalation(client,monkeypatch):
    class Clarifier:
        def select(self,q,c): return Decision(understanding=q,kind="clarify",clarification="object",evidence_ids=[])
    monkeypatch.setattr(jana,"LocalReader",lambda s:Clarifier())
    result=client.post("/api/v1/ai/ask",json={"question":"Почему так получилось?"}).json()
    assert not result["grounded"] and not result["escalation_suggested"]


def test_model_failure_is_not_a_fabricated_answer(client,monkeypatch):
    def broken(settings): raise JanaUnavailable("No model")
    monkeypatch.setattr(jana,"LocalReader",broken)
    assert client.post("/api/v1/ai/ask",json={"question":"Как оформить отпуск?"}).status_code==503


def test_kazakh_interface_preserves_literal_russian_evidence(client):
    result=client.post("/api/v1/ai/ask",json={"question":"Демалысты кім бекітеді?"},headers={"Accept-Language":"kk"})
    assert result.status_code==200
    assert result.json()["sources"][0]["excerpt"] in ARTICLE["content"]
    assert "орыс тілі" in result.json()["answer"]
