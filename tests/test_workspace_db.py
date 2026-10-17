"""Real transactions and access boundaries for stages 7, 8 and 10."""

from contextlib import contextmanager
from datetime import date, timedelta
from uuid import uuid4
import pytest
from psycopg.types.json import Jsonb
from test_request_workflow_db import (
    DATABASE_URL,
    MIGRATIONS,
    db as legacy_db,
    sqlstate,
    create_request,
    review_request,
)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="Set POSTTECH_TEST_DATABASE_URL"
)


@pytest.fixture(scope="module")
def db():
    with contextmanager(legacy_db.__wrapped__)() as database:
        with database.connect(None) as c:
            for name in (
                "0003_request_lifecycle.sql",
                "0004_academy_workflow.sql",
                "0007_delegation_learning_support.sql",
                "0008_course_seed_compatibility.sql",
            ):
                c.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
        yield database


def grant(c, p, **changes):
    values = dict(
        actor=p["hr"],
        id=str(uuid4()),
        manager=p["manager"],
        deputy=p["other_manager"],
        start=date.today(),
        end=date.today() + timedelta(days=5),
        reason="Test",
        revoke=False,
    )
    values.update(changes)
    return c.execute(
        "select manage_approval_delegation(%s,%s,%s,%s,%s,%s,%s,%s)",
        tuple(values.values()),
    ).fetchone()[0]


def test_delegation_permissions_expiry_self_and_audit(db):
    p = db.people
    with db.connect() as c:
        with sqlstate("PT403"):
            grant(c, p, actor=p["worker"])
        with sqlstate("PT422"):
            grant(c, p, deputy=p["manager"])
        d = grant(c, p)
        assert grant(c, p, id=d["id"])["id"] == d["id"]
        with sqlstate("PT409"):
            grant(c, p, manager=p["other_manager"], deputy=p["manager"])
        r = create_request(
            c,
            p["worker"],
            request_type="advance",
            start_date=None,
            end_date=None,
            amount=1000,
        )
        with sqlstate("PT403"):
            review_request(c, p["worker"], r["id"])
        reviewed = review_request(c, p["other_manager"], r["id"])
        assert reviewed["status"] == "approved"
        assert (
            str(
                c.execute(
                    "select delegation_id from request_events where request_id=%s and event_type='approved'",
                    (r["id"],),
                ).fetchone()[0]
            )
            == d["id"]
        )
        own = create_request(
            c,
            p["other_manager"],
            request_type="advance",
            start_date=None,
            end_date=None,
            amount=1100,
        )
        with sqlstate("PT403"):
            review_request(c, p["other_manager"], own["id"])
        pending = create_request(
            c,
            p["worker"],
            request_type="advance",
            start_date=None,
            end_date=None,
            amount=1200,
        )
        grant(c, p, id=d["id"], revoke=True)
        with sqlstate("PT403"):
            review_request(c, p["other_manager"], pending["id"])
        # Decision retries remain safe after revocation; no new event/notification.
        assert review_request(c, p["other_manager"], r["id"])["status"] == "approved"
        future = grant(
            c,
            p,
            start=date.today() + timedelta(days=2),
            end=date.today() + timedelta(days=5),
        )
        assert (
            c.execute(
                "select * from active_delegation_principals(%s)", (p["other_manager"],)
            ).fetchall()
            == []
        )
        grant(c, p, id=future["id"], revoke=True)


def content():
    return dict(
        title="Test course",
        description="Test",
        material_markdown="Read this material",
        duration_minutes=10,
        category="Test",
        audience="All",
        passing_score=80,
        quiz=[
            dict(
                id="q1",
                prompt="Choose the first option",
                options=["First", "Second"],
                answer_index=0,
            )
        ],
        translations={},
    )


def edit(c, p, id, action="create", revision=0, data=None):
    return c.execute(
        "select edit_academy_course(%s,%s,%s,%s,%s)",
        (p["hr"], id, action, revision, Jsonb(data or content())),
    ).fetchone()[0]


def test_course_versions_deadline_and_archived_completion(db):
    p = db.people
    id = str(uuid4())
    with db.connect() as c:
        draft = edit(c, p, id)
        with sqlstate("PT409"):
            edit(c, p, id, "save", 99)
        published = edit(c, p, id, "publish", draft["revision"])
        with sqlstate("PT409"):
            edit(c, p, id, "save", published["revision"])
        a = c.execute(
            "select assign_academy_course_due(%s,%s,%s,%s)",
            (p["manager"], p["worker"], id, date.today() + timedelta(days=2)),
        ).fetchone()[0]
        with sqlstate("PT403"):
            c.execute(
                "select set_course_deadline(%s,%s,%s)",
                (p["other_manager"], a["id"], date.today()),
            )
        v2 = edit(
            c,
            p,
            str(uuid4()),
            data={**content(), "family_id": id, "title": "Version two"},
        )
        edit(c, p, v2["id"], "publish", v2["revision"])
        assert c.execute(
            "select active from courses where id=%s", (id,)
        ).fetchone() == (False,)
        assert (
            str(
                c.execute(
                    "select course_id from course_assignments where id=%s", (a["id"],)
                ).fetchone()[0]
            )
            == id
        )
        c.execute("select update_academy_progress(%s,%s,90)", (p["worker"], id))
        result = c.execute(
            "select submit_academy_quiz(%s,%s,%s,%s)",
            (p["worker"], id, Jsonb({"q1": 0}), str(uuid4())),
        ).fetchone()[0]
        assert result["status"] == "completed"
        with sqlstate("PT409"):
            c.execute(
                "select set_course_deadline(%s,%s,%s)", (p["hr"], a["id"], date.today())
            )


def test_tickets_consent_idempotency_and_answer_permissions(db):
    p = db.people
    id = str(uuid4())
    with db.connect() as c:
        params = (p["worker"], id, "Help with schedule", "Only selected context")
        with sqlstate("PT422"):
            c.execute("select create_hr_ticket(%s,%s,%s,%s,false)", params)
        first = c.execute(
            "select create_hr_ticket(%s,%s,%s,%s,true)", params
        ).fetchone()[0]
        assert (
            c.execute("select create_hr_ticket(%s,%s,%s,%s,true)", params).fetchone()[0]
            == first
        )
        with sqlstate("PT409"):
            c.execute(
                "select create_hr_ticket(%s,%s,%s,%s,true)",
                (p["outsider"], *params[1:]),
            )
        with sqlstate("PT403"):
            c.execute("select answer_hr_ticket(%s,%s,%s)", (p["manager"], id, "Answer"))
        reply = c.execute(
            "select answer_hr_ticket(%s,%s,%s)", (p["hr"], id, "Confirmed answer")
        ).fetchone()[0]
        assert reply["status"] == "resolved"
        assert (
            c.execute(
                "select answer_hr_ticket(%s,%s,%s)", (p["hr"], id, "Confirmed answer")
            ).fetchone()[0]
            == reply
        )
        with sqlstate("PT409"):
            c.execute(
                "select answer_hr_ticket(%s,%s,%s)", (p["hr"], id, "Changed answer")
            )
        assert c.execute(
            "select count(*) from notifications where ticket_id=%s and notification_type='hr_ticket_answered'",
            (id,),
        ).fetchone() == (1,)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_cannot_read_private_tables_or_impersonate(db, role):
    with db.connect(role) as c:
        for table in ["approval_delegations", "course_deadline_events", "hr_tickets"]:
            with sqlstate("42501"):
                c.execute(f"select * from {table}")
        with sqlstate("42501"):
            c.execute(
                "select active_delegation_principals(%s)", (db.people["manager"],)
            )


def test_legacy_seed_course_gets_version_family(db):
    with db.connect() as c:
        row = c.execute(
            "insert into courses(title,description,duration_minutes,material_markdown,quiz) values('Legacy import','Test',5,'Material','[]') returning family_id,version"
        ).fetchone()
        assert row[0] is not None and row[1] == 1
