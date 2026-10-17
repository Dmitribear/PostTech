"""Transactional leave holds, outbox leases, versioned lessons and HR sources."""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
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
            for number in ("0003", "0004", "0006", "0007", "0008", "0009", "0010"):
                c.execute(
                    next(MIGRATIONS.glob(number + "*.sql")).read_text(encoding="utf-8")
                )
        yield database


def advance(c, p):
    return create_request(
        c,
        p["worker"],
        request_type="advance",
        start_date=None,
        end_date=None,
        amount=1234,
    )


def test_leave_reserves_releases_and_reconciles_once(db):
    p = db.people
    with db.connect() as c:
        start = date.today() + timedelta(days=90)
        r = create_request(
            c, p["worker"], start_date=start, end_date=start + timedelta(days=4)
        )
        assert c.execute(
            "select days,state from leave_holds where request_id=%s", (r["id"],)
        ).fetchone() == (5, "pending")
        review_request(c, p["manager"], r["id"])
        assert (
            c.execute(
                "select vacation_days_remaining from employee_profiles where id=%s",
                (p["worker"],),
            ).fetchone()[0]
            == 24
        )
        assert (
            c.execute(
                "select state from leave_holds where request_id=%s", (r["id"],)
            ).fetchone()[0]
            == "approved"
        )
        key = uuid4()
        args = (p["hr"], key, p["worker"], 19, [r["id"]], "Verified payroll snapshot")
        with sqlstate("PT403"):
            c.execute(
                "select reconcile_leave_balance(%s,%s,%s,%s,%s::uuid[],%s)",
                (p["worker"], *args[1:]),
            )
        for _ in range(2):
            assert (
                c.execute(
                    "select reconcile_leave_balance(%s,%s,%s,%s,%s::uuid[],%s)", args
                ).fetchone()[0]["official_days"]
                == 19
            )
        assert (
            c.execute(
                "select state from leave_holds where request_id=%s", (r["id"],)
            ).fetchone()[0]
            == "reconciled"
        )
        assert (
            c.execute(
                "select count(*) from leave_balance_events where id=%s", (key,)
            ).fetchone()[0]
            == 1
        )
        r2 = create_request(
            c,
            p["worker"],
            start_date=start + timedelta(days=8),
            end_date=start + timedelta(days=9),
        )
        c.execute("select cancel_hr_request(%s,%s)", (p["worker"], r2["id"]))
        assert (
            c.execute(
                "select state from leave_holds where request_id=%s", (r2["id"],)
            ).fetchone()[0]
            == "released"
        )


def test_concurrent_nonoverlapping_leave_cannot_overbook(db):
    p = db.people
    start = date.today() + timedelta(days=140)

    def submit(i):
        with db.connect() as c:
            try:
                return create_request(
                    c,
                    p["outsider"],
                    start_date=start + timedelta(days=i * 20),
                    end_date=start + timedelta(days=i * 20 + 12),
                )["id"]
            except Exception as e:
                return e.sqlstate

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, [0, 1]))
    assert results.count("PT409") == 1
    with db.connect() as c:
        assert (
            c.execute(
                "select sum(days) from leave_holds where employee_id=%s and state='pending'",
                (p["outsider"],),
            ).fetchone()[0]
            == 13
        )
        successful = next(r for r in results if r != "PT409")
        review_request(
            c, p["other_manager"], successful, "rejected", "Capacity test cleanup"
        )
        assert (
            c.execute(
                "select state from leave_holds where request_id=%s", (successful,)
            ).fetchone()[0]
            == "released"
        )


def test_outbox_atomic_deduplicated_and_no_self_approval(db):
    p = db.people
    with db.connect() as c:
        r = advance(c, p)
        with sqlstate("PT403"):
            review_request(c, p["worker"], r["id"])
        assert (
            c.execute(
                "select count(*) from integration_outbox where aggregate_id=%s",
                (r["id"],),
            ).fetchone()[0]
            == 0
        )
        c.execute("set posttech_test.fail_notifications='on'")
        with pytest.raises(Exception):
            review_request(c, p["manager"], r["id"])
        c.execute("set posttech_test.fail_notifications='off'")
        assert (
            c.execute(
                "select count(*) from integration_outbox where aggregate_id=%s",
                (r["id"],),
            ).fetchone()[0]
            == 0
        )
        review_request(c, p["manager"], r["id"])
        review_request(c, p["manager"], r["id"])
        assert (
            c.execute(
                "select count(*) from integration_outbox where aggregate_id=%s",
                (r["id"],),
            ).fetchone()[0]
            == 2
        )
        payload = c.execute(
            "select payload from integration_outbox where aggregate_id=%s limit 1",
            (r["id"],),
        ).fetchone()[0]
        assert "comment" not in payload and payload["schema_version"] == 1


def test_outbox_lease_retry_stale_worker_and_ack(db):
    with db.connect() as c:
        event = c.execute("select claim_integration_event('1c')").fetchone()[0]
        assert event and event["attempts"] == 1
        c.execute(
            "update integration_outbox set lease_until=now()-interval '1 minute' where id=%s",
            (event["id"],),
        )
        # Make this expired event first in the queue.
        c.execute(
            "update integration_outbox set next_attempt_at=now()-interval '1 day' where id=%s",
            (event["id"],),
        )
        next_event = c.execute("select claim_integration_event('1c')").fetchone()[0]
        assert (
            next_event["id"] == event["id"]
            and next_event["lease_token"] != event["lease_token"]
        )
        with sqlstate("PT409"):
            c.execute(
                "select finish_integration_event(%s,%s,true,null)",
                (event["id"], event["lease_token"]),
            )
        failed = c.execute(
            "select finish_integration_event(%s,%s,false,%s)",
            (event["id"], next_event["lease_token"], "HTTP 503"),
        ).fetchone()[0]
        assert failed["status"] == "retry"
        c.execute(
            "select retry_integration_event(%s,%s)", (db.people["hr"], event["id"])
        )
        c.execute(
            "update integration_outbox set next_attempt_at=now()-interval '1 day' where id=%s",
            (event["id"],),
        )
        retry = c.execute("select claim_integration_event('1c')").fetchone()[0]
        assert retry["id"] == event["id"]
        delivered = c.execute(
            "select finish_integration_event(%s,%s,true,null)",
            (event["id"], retry["lease_token"]),
        ).fetchone()[0]
        assert delivered["status"] == "delivered"
        with sqlstate("PT409"):
            c.execute(
                "select retry_integration_event(%s,%s)", (db.people["hr"], event["id"])
            )


def test_parallel_claims_are_distinct(db):
    def claim(_):
        with db.connect() as c:
            return c.execute(
                "select claim_integration_event('documentolog')"
            ).fetchone()[0]

    with ThreadPoolExecutor(3) as pool:
        rows = [x for x in pool.map(claim, range(3)) if x]
    assert len(rows) >= 2 and len({x["id"] for x in rows}) == len(rows)


def test_lessons_gate_quiz_resume_and_version_immutability(db):
    from test_workspace_db import content

    p = db.people
    course = str(uuid4())
    data = content()
    data["lessons"] = [
        dict(id="first", title="First lesson", material_markdown="First content"),
        dict(id="second", title="Second lesson", material_markdown="Second content"),
    ]
    with db.connect() as c:
        draft = c.execute(
            "select edit_academy_course(%s,%s,%s,0,%s)",
            (p["hr"], course, "create", Jsonb(data)),
        ).fetchone()[0]
        assert len(draft["lessons"]) == 2
        published = c.execute(
            "select edit_academy_course(%s,%s,%s,%s,%s)",
            (p["hr"], course, "publish", draft["revision"], Jsonb({})),
        ).fetchone()[0]
        c.execute(
            "select assign_academy_course(%s,%s,%s)",
            (p["manager"], p["worker"], course),
        )
        with sqlstate("PT409"):
            c.execute("select update_academy_progress(%s,%s,90)", (p["worker"], course))
        with sqlstate("PT404"):
            c.execute(
                "select complete_academy_lesson(%s,%s,%s)",
                (p["outsider"], course, "first"),
            )
        for _ in range(2):
            first = c.execute(
                "select complete_academy_lesson(%s,%s,%s)",
                (p["worker"], course, "first"),
            ).fetchone()[0]
            assert first["progress_percent"] == 45 and first[
                "completed_lesson_ids"
            ] == ["first"]
        with sqlstate("PT409"):
            c.execute(
                "select submit_academy_quiz(%s,%s,%s,%s)",
                (p["worker"], course, Jsonb({"q1": 0}), uuid4()),
            )
        c.execute(
            "select complete_academy_lesson(%s,%s,%s)", (p["worker"], course, "second")
        )
        result = c.execute(
            "select submit_academy_quiz(%s,%s,%s,%s)",
            (p["worker"], course, Jsonb({"q1": 0}), uuid4()),
        ).fetchone()[0]
        assert result["status"] == "completed"
        with sqlstate("PT409"):
            c.execute(
                "select edit_academy_course(%s,%s,%s,%s,%s)",
                (p["hr"], course, "save", published["revision"], Jsonb(data)),
            )
        # A retried create must never overwrite existing published lessons.
        data["lessons"] = []
        same = c.execute(
            "select edit_academy_course(%s,%s,%s,0,%s)",
            (p["hr"], course, "create", Jsonb(data)),
        ).fetchone()[0]
        assert len(same["lessons"]) == 2


def test_knowledge_draft_review_revision_and_archive(db):
    p = db.people
    id = uuid4()
    data = dict(
        title="Leave policy",
        content="Approved policy text",
        source_title="HR policy 2026",
        keywords=["leave"],
        source_url=None,
    )

    def command(c, action, revision=0, actor=None, body=None):
        return c.execute(
            "select edit_knowledge_article(%s,%s,%s,%s,%s,%s)",
            (
                actor or p["hr"],
                id,
                action,
                revision,
                Jsonb(body or data),
                date.today() + timedelta(days=30),
            ),
        ).fetchone()[0]

    with db.connect() as c:
        with sqlstate("PT403"):
            command(c, "create", actor=p["manager"])
        draft = command(c, "create")
        assert not draft["active"]
        published = command(c, "approve", draft["revision"])
        assert published["active"] and published["reviewed_at"]
        changed = command(
            c, "save", published["revision"], body={**data, "content": "Changed draft"}
        )
        assert (
            changed["content"] == "Approved policy text"
            and changed["draft"]["content"] == "Changed draft"
        )
        with sqlstate("PT409"):
            command(c, "approve", published["revision"])
        updated = command(c, "approve", changed["revision"])
        assert (
            updated["content"] == "Changed draft"
            and updated["reviewed_at"]
            and updated["version"] != published["version"]
        )
        assert not command(c, "archive", updated["revision"])["active"]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_cannot_mutate_extensions(db, role):
    with db.connect(role) as c:
        with sqlstate("42501"):
            c.execute("select claim_integration_event('1c')")
        with sqlstate("42501"):
            c.execute("select * from leave_holds")
        with sqlstate("42501"):
            c.execute("select * from knowledge_events")
