from contextlib import contextmanager
from datetime import date, timedelta
from uuid import uuid4

import pytest

from test_consolidated_schema_db import db as consolidated_database
from test_request_workflow_db import (
    DATABASE_URL,
    MIGRATIONS,
    create_request,
    review_request,
    sqlstate,
)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="Set POSTTECH_TEST_DATABASE_URL"
)


@pytest.fixture(scope="module")
def db():
    with contextmanager(consolidated_database.__wrapped__)() as database:
        with database.connect(None) as connection:
            for number in (17, 18):
                connection.execute(
                    next(MIGRATIONS.glob(f"{number:04d}*.sql")).read_text(
                        encoding="utf-8"
                    )
                )
        yield database


@pytest.fixture
def connection(db):
    with db.connect() as connection:
        with connection.transaction(force_rollback=True):
            yield connection


def balance(connection, employee_id):
    return connection.execute(
        "select read_leave_balance(%s)", (employee_id,)
    ).fetchone()[0]


def leave(connection, db):
    start = date.today() + timedelta(days=600)
    return create_request(
        connection,
        db.people["worker"],
        start_date=start,
        end_date=start + timedelta(days=2),
    )


def cancel(connection, db, request_id):
    return connection.execute(
        "select cancel_hr_request(%s,%s)", (db.people["worker"], request_id)
    ).fetchone()[0]


def delegate(connection, db, *, future=False):
    start = date.today() + timedelta(days=2 if future else 0)
    return connection.execute(
        "select manage_approval_delegation(%s,%s,%s,%s,%s,%s,%s,false)",
        (
            db.people["hr"],
            str(uuid4()),
            db.people["manager"],
            db.people["other_manager"],
            start,
            start + timedelta(days=5),
            "Cancellation notification test",
        ),
    ).fetchone()[0]


def cancellation_recipients(connection, request_id):
    return [
        row[0]
        for row in connection.execute(
            "select employee_id::text from notifications "
            "where request_id=%s and notification_type='request_cancelled'",
            (request_id,),
        ).fetchall()
    ]


@pytest.mark.parametrize("terminal", ["cancelled", "rejected"])
def test_terminal_leave_releases_exactly_reserved_days(db, connection, terminal):
    p = db.people
    before = balance(connection, p["worker"])
    request = leave(connection, db)
    assert (
        balance(connection, p["worker"])["available_days"]
        == before["available_days"] - 3
    )
    for _ in range(2):
        if terminal == "cancelled":
            result = cancel(connection, db, request["id"])
        else:
            result = review_request(
                connection,
                p["manager"],
                request["id"],
                terminal,
                "Choose different dates",
            )
        assert result["status"] == terminal
        assert balance(connection, p["worker"]) == before
    assert connection.execute(
        "select days,state from leave_holds where request_id=%s", (request["id"],)
    ).fetchone() == (3, "released")
    assert connection.execute(
        "select count(*) from request_events where request_id=%s and event_type=%s",
        (request["id"], terminal),
    ).fetchone()[0] == 1
    assert leave(connection, db)["id"] != request["id"]


@pytest.mark.parametrize("role", ["manager", "director", "hr_admin"])
def test_cancel_notifies_active_deputy_once(db, connection, role):
    p = db.people
    connection.execute(
        "select assign_employee_role(%s,%s,%s)", (p["hr"], p["other_manager"], role)
    )
    delegate(connection, db)
    request = leave(connection, db)
    cancel(connection, db, request["id"])
    cancel(connection, db, request["id"])
    recipients = cancellation_recipients(connection, request["id"])
    assert set(recipients) == {p["worker"], p["manager"], p["other_manager"]}
    assert len(recipients) == 3


@pytest.mark.parametrize("inactive", ["future", "revoked", "on_leave"])
def test_cancel_does_not_notify_inactive_deputy(db, connection, inactive):
    p = db.people
    delegation = delegate(connection, db, future=inactive == "future")
    if inactive == "revoked":
        connection.execute(
            "select manage_approval_delegation(%s,%s,%s,%s,%s,%s,%s,true)",
            (
                p["hr"],
                delegation["id"],
                p["manager"],
                p["other_manager"],
                delegation["starts_on"],
                delegation["ends_on"],
                delegation["reason"],
            ),
        )
    elif inactive == "on_leave":
        deputy_leave = create_request(
            connection, p["other_manager"], start_date=date.today(), end_date=date.today()
        )
        review_request(connection, p["hr"], deputy_leave["id"])
    request = leave(connection, db)
    cancel(connection, db, request["id"])
    assert set(cancellation_recipients(connection, request["id"])) == {
        p["worker"], p["manager"]
    }


def test_notification_failure_keeps_leave_reserved_then_retry_releases(db, connection):
    p = db.people
    delegate(connection, db)
    before = balance(connection, p["worker"])
    request = leave(connection, db)
    pending = balance(connection, p["worker"])
    connection.execute("set posttech_test.fail_notifications='on'")
    with sqlstate("P0001"):
        with connection.transaction():
            cancel(connection, db, request["id"])
    connection.execute("set posttech_test.fail_notifications='off'")
    assert balance(connection, p["worker"]) == pending
    assert connection.execute(
        "select status::text from hr_requests where id=%s", (request["id"],)
    ).fetchone()[0] == "pending"
    assert cancellation_recipients(connection, request["id"]) == []
    cancel(connection, db, request["id"])
    assert balance(connection, p["worker"]) == before
    assert len(cancellation_recipients(connection, request["id"])) == 3
