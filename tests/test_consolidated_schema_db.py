from contextlib import contextmanager

import pytest

from test_hr_workflows_db import db as workflow_database
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
    with contextmanager(workflow_database.__wrapped__)() as database:
        with database.connect(None) as connection:
            for number in range(13, 17):
                connection.execute(
                    next(MIGRATIONS.glob(f"{number:04d}*.sql")).read_text(
                        encoding="utf-8"
                    )
                )
        yield database


def test_director_reviews_team_leave_once_without_double_deduction(db):
    p = db.people
    with db.connect() as c:
        c.execute(
            "select assign_employee_role(%s,%s,'director')", (p["hr"], p["manager"])
        )
        before = c.execute("select read_leave_balance(%s)", (p["worker"],)).fetchone()[
            0
        ]
        request = create_request(c, p["worker"])
        routing = c.execute(
            "select get_hr_request_routing(%s)", (p["worker"],)
        ).fetchone()[0]
        assert any(person["id"] == p["manager"] for person in routing["approvers"])
        review_request(c, p["manager"], request["id"])
        review_request(c, p["manager"], request["id"])
        after = c.execute("select read_leave_balance(%s)", (p["worker"],)).fetchone()[0]
        assert before["available_days"] - after["available_days"] == 5
        assert before["official_days"] == after["official_days"]
        assert c.execute(
            "select days,state from leave_holds where request_id=%s", (request["id"],)
        ).fetchone() == (5, "approved")
        assert (
            c.execute(
                "select count(*) from employee_role_changes where employee_id=%s",
                (p["manager"],),
            ).fetchone()[0]
            == 1
        )


def test_director_own_leave_is_reviewed_by_hr(db):
    with db.connect() as c:
        request = create_request(c, db.people["manager"])
        with sqlstate("PT403"):
            review_request(c, db.people["manager"], request["id"])
        assert review_request(c, db.people["hr"], request["id"])["status"] == "approved"


def test_role_change_requires_hr_and_preserves_reporting_line(db):
    p = db.people
    with db.connect() as c:
        with sqlstate("42501"):
            c.execute(
                "select assign_employee_role(%s,%s,'hr_admin')",
                (p["worker"], p["worker"]),
            )
        with sqlstate("PT409"):
            c.execute("select assign_employee_role(%s,%s,'worker')", (p["hr"], p["hr"]))
        with sqlstate("PT412"):
            c.execute(
                "select assign_employee_role(%s,%s,'worker')", (p["hr"], p["manager"])
            )


def test_browser_roles_cannot_call_role_mutation(db):
    for role in ("anon", "authenticated"):
        with db.connect(role) as c, sqlstate("42501"):
            c.execute(
                "select assign_employee_role(%s,%s,'director')",
                (db.people["hr"], db.people["worker"]),
            )


def test_director_invitation_preserves_hr_assigned_role(db):
    from test_registration_db import issue, prepare, complete, add_user
    with db.connect() as c:
        token, invitation, details = issue(c, db, role='director', manager_id=None)
        prepare(c, token)
        user = add_user(db, details['email'])
        result = complete(c, token, user)
        assert result['role'] == 'director'
        assert complete(c, token, user) == result
