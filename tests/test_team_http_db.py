"""HTTP contracts through real local SQL; only identity and transport are replaced.

These are not Supabase Auth/PostgREST end-to-end tests. The adapter executes
actual workflow functions and SELECTs as service_role in a disposable database.
"""
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg", reason="Install tests/requirements-db.txt")
from psycopg import sql
from fastapi.testclient import TestClient
from icalendar import Calendar
from postgrest.exceptions import APIError

from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext
from app.services import requests as workflow
from test_request_workflow_db import DATABASE_URL
from test_team_workflow_db import team_db, add_person

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Set POSTTECH_TEST_DATABASE_URL")


def execute(database, statement, values, *, rpc=False):
    try:
        with database.connect() as connection:
            rows = connection.execute(statement, values).fetchall()
            return SimpleNamespace(data=rows[0][0] if rpc else [row[0] for row in rows])
    except psycopg.Error as exc:
        # PostgREST represents these same SQLSTATEs as APIError. No network call.
        raise APIError({"code": exc.sqlstate or "XX000", "message": exc.diag.message_primary,
                        "details": None, "hint": None}) from exc


class SqlTable:
    def __init__(self, database, name):
        assert name in {"hr_requests", "request_events", "employee_profiles", "knowledge_articles"}
        self.database, self.name = database, name
        self.columns, self.filters, self.values, self.orders = [], [], [], []
        self.bounds = None

    def select(self, columns):
        self.columns = columns.split(",")
        assert all(name.replace("_", "").isalnum() for name in self.columns)
        return self

    def eq(self, column, value):
        self.filters.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
        self.values.append(value)
        return self

    def order(self, column, desc=False):
        self.orders.append(sql.SQL("{} {}").format(sql.Identifier(column), sql.SQL("DESC" if desc else "ASC")))
        return self

    def limit(self, count):
        return self.range(0, count - 1)

    def range(self, start, end):
        self.bounds = (end - start + 1, start)
        return self

    def execute(self):
        statement = sql.SQL("SELECT {} FROM public.{}").format(
            sql.SQL(",").join(map(sql.Identifier, self.columns)), sql.Identifier(self.name)
        )
        values = list(self.values)
        if self.filters:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(self.filters)
        if self.orders:
            statement += sql.SQL(" ORDER BY ") + sql.SQL(",").join(self.orders)
        if self.bounds:
            statement += sql.SQL(" LIMIT %s OFFSET %s")
            values.extend(self.bounds)
        # JSON conversion mirrors PostgREST date/UUID serialization.
        return execute(self.database, sql.SQL("SELECT to_jsonb(r) FROM ({}) r").format(statement), values)


class SqlTransport:
    def __init__(self, database):
        self.database = database

    def table(self, name):
        return SqlTable(self.database, name)

    def rpc(self, name, params):
        assert name in {"create_hr_request", "review_hr_request", "cancel_hr_request", "active_delegation_principals"}
        if name == "active_delegation_principals":
            statement = sql.SQL("SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM public.{}(%s) t").format(sql.Identifier(name))
        else:
            arguments = sql.SQL(",").join(sql.SQL("{} => %s").format(sql.Identifier(key)) for key in params)
            statement = sql.SQL("SELECT public.{}({})").format(sql.Identifier(name), arguments)
        return SimpleNamespace(execute=lambda: execute(self.database, statement, list(params.values()), rpc=True))


@pytest.fixture
def api(team_db, monkeypatch):
    identity = {}
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    monkeypatch.setattr(workflow, "get_supabase_client", lambda: SqlTransport(team_db))
    try:
        with TestClient(app) as client:
            yield client, team_db, identity
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def login(identity, person, role):
    # This selects an already-proven identity; it does not simulate password login.
    identity["user"] = UserContext(id=person, auth_user_id=person, role=role)


def people(database, *, reviewer_role="manager", balance=24):
    with database.connect(None) as connection:
        reviewer = add_person(connection, role=reviewer_role)
        hr = add_person(connection, role="hr_admin")
        worker = add_person(connection, manager_id=reviewer, balance=balance)
        outsider = add_person(connection)
    return worker, reviewer, hr, outsider


def leave_payload():
    start = date.today() + timedelta(days=70)
    return {"request_type": "leave", "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=2)).isoformat(), "comment": "Local integration test"}


@pytest.mark.parametrize("reviewer_role", ["manager", "director"])
def test_http_leave_approval_balance_sources_and_calendar(api, reviewer_role):
    client, database, identity = api
    worker, reviewer, hr, outsider = people(database, reviewer_role=reviewer_role)
    login(identity, worker, "worker")
    payload, key = leave_payload(), str(uuid4())
    created = client.post("/api/v1/requests", json=payload, headers={"Idempotency-Key": key})
    assert created.status_code == 201, created.text
    request = created.json()
    assert request["status"] == "pending"
    request_id = request["id"]
    assert client.post("/api/v1/requests", json=payload, headers={"Idempotency-Key": key}).json()["id"] == request_id
    assert client.get(f"/api/v1/requests/{request_id}/calendar.ics").status_code == 409
    assert [row["id"] for row in client.get("/api/v1/requests?scope=mine").json()] == [request_id]
    assert client.patch(f"/api/v1/requests/{request_id}/review", json={"status": "approved"}).status_code == 403

    login(identity, reviewer, reviewer_role)
    first = client.patch(f"/api/v1/requests/{request_id}/review", json={"status": "approved"})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "pending_hr"
    assert client.get(f"/api/v1/requests/{request_id}/calendar.ics").status_code == 409
    with database.connect() as connection:
        assert connection.execute("SELECT vacation_days_remaining FROM employee_profiles WHERE id=%s", (worker,)).fetchone()[0] == 24

    login(identity, hr, "hr_admin")
    for _ in range(2):
        final = client.patch(f"/api/v1/requests/{request_id}/review", json={"status": "approved"})
        assert final.status_code == 200, final.text
        assert final.json()["status"] == "approved"
    with database.connect() as connection:
        assert connection.execute("SELECT vacation_days_remaining FROM employee_profiles WHERE id=%s", (worker,)).fetchone()[0] == 21
        assert connection.execute("SELECT count(*) FROM request_events WHERE request_id=%s AND event_type='approved'", (request_id,)).fetchone()[0] == 1

    login(identity, worker, "worker")
    assert client.get(f"/api/v1/requests/{request_id}").json()["status"] == "approved"
    events = client.get(f"/api/v1/requests/{request_id}/history")
    assert events.status_code == 200, events.text
    assert [event["event_type"] for event in events.json()] == ["created", "pending_hr", "approved"]
    exported = client.get(f"/api/v1/requests/{request_id}/calendar.ics")
    assert exported.status_code == 200, exported.text
    event = Calendar.from_ical(exported.content).walk("VEVENT")[0]
    assert event.decoded("dtstart") == date.fromisoformat(payload["start_date"])
    assert event.decoded("dtend") == date.fromisoformat(payload["end_date"]) + timedelta(days=1)
    assert client.post(f"/api/v1/requests/{request_id}/cancel").status_code == 409

    login(identity, outsider, "worker")
    assert client.get("/api/v1/requests?scope=mine").json() == []
    for suffix in ("", "/history", "/calendar.ics"):
        assert client.get(f"/api/v1/requests/{request_id}{suffix}").status_code == 403


def test_http_insufficient_balance_and_cancel_are_atomic(api):
    client, database, identity = api
    worker, reviewer, hr, outsider = people(database)
    login(identity, worker, "worker")
    created = client.post("/api/v1/requests", json=leave_payload())
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    login(identity, reviewer, "manager")
    assert client.patch(f"/api/v1/requests/{request_id}/review", json={"status": "approved"}).json()["status"] == "pending_hr"
    with database.connect(None) as connection:
        connection.execute("UPDATE employee_profiles SET vacation_days_remaining=1 WHERE id=%s", (worker,))
    login(identity, hr, "hr_admin")
    response = client.patch(f"/api/v1/requests/{request_id}/review", json={"status": "approved"})
    assert response.status_code == 409, response.text
    with database.connect() as connection:
        assert connection.execute("SELECT status FROM hr_requests WHERE id=%s", (request_id,)).fetchone()[0] == "pending_hr"
        assert connection.execute("SELECT vacation_days_remaining FROM employee_profiles WHERE id=%s", (worker,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM request_events WHERE request_id=%s AND event_type='approved'", (request_id,)).fetchone()[0] == 0
    login(identity, outsider, "worker")
    assert client.post(f"/api/v1/requests/{request_id}/cancel").status_code == 403
    login(identity, worker, "worker")
    for _ in range(2):
        cancelled = client.post(f"/api/v1/requests/{request_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
    with database.connect() as connection:
        assert connection.execute("SELECT state FROM leave_holds WHERE request_id=%s", (request_id,)).fetchone()[0] == "released"
        assert connection.execute("SELECT vacation_days_remaining FROM employee_profiles WHERE id=%s", (worker,)).fetchone()[0] == 1


def test_jana_seed_publication_citations_and_source_version_through_sql(api, monkeypatch):
    """The SQL seed, publication filter and quoted HTTP response share one snapshot."""
    from app.services import jana
    from app.services.jana_intent import Decision
    from app.services.jana_knowledge import FIELDS

    client, database, identity = api
    root = Path(__file__).resolve().parents[1]
    with database.connect(None) as connection:
        for email in ("hr@posttech.demo", "director@posttech.demo", "manager@posttech.demo", "employee@posttech.demo"):
            connection.execute("INSERT INTO auth.users(id,email) VALUES (%s,%s)", (str(uuid4()), email))
        connection.execute((root / "database/seed.sql").read_text(encoding="utf-8"))
        seed = (root / "database/seed_jana_demo.sql").read_text(encoding="utf-8")
        connection.execute(seed)
        connection.execute(seed)
        assert connection.execute("""SELECT count(*) FROM knowledge_articles WHERE active
            AND editorial_state='published' AND reviewed_at IS NOT NULL
            AND review_due_at>reviewed_at""").fetchone()[0] == 13
        content = " ".join(row[0] for row in connection.execute("SELECT content FROM knowledge_articles"))
        assert "При окончательном одобрении дни списываются" in content
        assert "У курса есть свой проходной балл" in content
        assert "не списывает дни автоматически" not in content
        assert "Отдельный проходной балл не установлен" not in content
        # Keep publication-window checks deterministic after demo review expiry.
        connection.execute("UPDATE knowledge_articles SET reviewed_at=now()-interval '1 second', review_due_at=now()+interval '30 days'")
        worker = connection.execute("SELECT id::text FROM employee_profiles WHERE email='employee@posttech.demo'").fetchone()[0]
    login(identity, worker, "worker")
    queries = []

    class KnowledgeTransport(SqlTransport):
        def table(self, name):
            queries.append(name)
            assert name == "knowledge_articles", "Jana must not query personal HR tables"
            table = super().table(name)
            original_select = table.select

            def select(columns):
                assert columns == FIELDS
                return original_select(columns)
            table.select = select
            return table

        def rpc(self, name, params):
            pytest.fail("Jana must not call a personal-data or mutation RPC")

    class ReaderStub:
        def __init__(self, settings):
            pass

        def select(self, question, articles):
            assert len(articles) == 13
            if question == "Сколько дней у меня осталось?":
                return Decision(understanding="Запрос личного остатка", kind="personal", evidence_ids=[], clarification="none")
            article = next(a for a in articles if a["article_id"] == "20000000-0000-4000-8000-000000000001")
            evidence = next(span for span in article["sentences"] if "При окончательном одобрении дни списываются" in span["text"])
            return Decision(understanding="Когда списывают отпуск", kind="answer", evidence_ids=[evidence["id"]], clarification="none")

    monkeypatch.setattr(jana, "get_supabase_client", lambda: KnowledgeTransport(database))
    monkeypatch.setattr(jana, "LocalReader", ReaderStub)
    answered = client.post("/api/v1/ai/ask", json={"question": "Когда списывают дни отпуска?"})
    assert answered.status_code == 200, answered.text
    source = answered.json()["sources"][0]
    assert source["freshness"] == "reviewed" and source["version"] in source["url"]
    opened = client.get(source["url"])
    assert opened.status_code == 200, opened.text
    assert source["excerpt"] in opened.json()["content"]
    assert "списываются" in answered.json()["answer"]
    personal = client.post("/api/v1/ai/ask", json={"question": "Сколько дней у меня осталось?"})
    assert personal.status_code == 200 and personal.json()["sources"] == []
    assert personal.json()["mode"] == "refusal"
    with database.connect(None) as connection:
        connection.execute("UPDATE knowledge_articles SET content=content||' Новая редакция.' WHERE id=%s", (source["id"],))
    assert client.get(source["url"]).status_code == 404  # Edit clears the review.
    with database.connect(None) as connection:
        connection.execute("UPDATE knowledge_articles SET reviewed_at=now()-interval '1 second',review_due_at=now()+interval '30 days' WHERE id=%s", (source["id"],))
    assert client.get(source["url"]).status_code == 409
    assert client.get(f"/api/v1/ai/sources/{source['id']}").status_code == 200
    with database.connect(None) as connection:
        connection.execute("UPDATE knowledge_articles SET active=false,editorial_state='archived' WHERE id=%s", (source["id"],))
    assert client.get(source["url"]).status_code == 404
    assert set(queries) == {"knowledge_articles"}
