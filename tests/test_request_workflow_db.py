"""Opt-in integration tests against real PostgreSQL, in a disposable database.

Set POSTTECH_TEST_DATABASE_URL to an empty local database whose name starts with
``posttech_test_``. The connection user must be allowed to create databases and
roles. These tests create/drop only their own UUID-named database, never clear an
existing schema. Supabase Auth is represented only by its referenced users table;
the application's migrations, functions, constraints, locks and RLS are real.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest


DATABASE_URL = os.environ.get("POSTTECH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="Set POSTTECH_TEST_DATABASE_URL for real PostgreSQL tests"
)
MIGRATIONS = Path(__file__).resolve().parents[1] / "database" / "migrations"
DEFAULT_LEAVE = {
    "request_type": "leave",
    "start_date": "2026-11-02",
    "end_date": "2026-11-06",
    "amount": None,
    "comment": "Семейный отпуск",
}
GENERATE_KEY = object()


@dataclass
class WorkflowDatabase:
    dsn: str
    people: dict[str, str]
    legacy: dict[str, str]

    @contextmanager
    def connect(self, role="service_role"):
        import psycopg
        from psycopg import sql

        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute("SET statement_timeout = '15s'")
            connection.execute("SET lock_timeout = '10s'")
            connection.execute("SET TIME ZONE 'UTC'")
            if role:
                connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            yield connection


def create_request(connection, actor, key=GENERATE_KEY, **overrides):
    payload = DEFAULT_LEAVE | overrides
    return connection.execute(
        """SELECT public.create_hr_request(
            %s::uuid, %s::public.hr_request_type, %s::date, %s::date,
            %s::numeric, %s::text, %s::uuid
        )""",
        (
            actor,
            payload["request_type"],
            payload["start_date"],
            payload["end_date"],
            payload["amount"],
            payload["comment"],
            str(uuid4()) if key is GENERATE_KEY else key,
        ),
    ).fetchone()[0]


def review_request(connection, actor, request_id, status="approved", comment=None):
    return connection.execute(
        """SELECT public.review_hr_request(
            %s::uuid, %s::uuid, %s::public.hr_request_status, %s::text
        )""",
        (actor, request_id, status, comment),
    ).fetchone()[0]


def counts(connection, request_id):
    return connection.execute(
        """SELECT
            (SELECT count(*) FROM public.hr_requests WHERE id = %s),
            (SELECT count(*) FROM public.request_events WHERE request_id = %s),
            (SELECT count(*) FROM public.notifications WHERE request_id = %s)""",
        (request_id, request_id, request_id),
    ).fetchone()


@contextmanager
def sqlstate(expected):
    import psycopg

    with pytest.raises(psycopg.Error) as error:
        yield
    assert error.value.sqlstate == expected, str(error.value)


@pytest.fixture(scope="module")
def db():
    psycopg = pytest.importorskip("psycopg", reason="Install tests/requirements-db.txt")
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    options = conninfo_to_dict(DATABASE_URL)
    if not options.get("dbname", "").startswith("posttech_test_"):
        pytest.fail("POSTTECH_TEST_DATABASE_URL must name a posttech_test_* database")

    isolated_name = "posttech_test_" + uuid4().hex
    isolated_dsn = make_conninfo(DATABASE_URL, dbname=isolated_name)
    people = {
        name: str(uuid4())
        for name in ("manager", "other_manager", "hr", "worker", "outsider", "orphan")
    }
    legacy = {status: str(uuid4()) for status in ("pending", "approved", "rejected")}

    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        if admin.execute("SELECT to_regclass('public.employee_profiles')").fetchone()[
            0
        ]:
            pytest.fail(
                "Refusing an existing application database; use an empty test database"
            )

        # Roles are cluster-wide. Never change or remove an existing role.
        for role in ("anon", "authenticated", "service_role"):
            existing = admin.execute(
                "SELECT rolcanlogin, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = %s",
                (role,),
            ).fetchone()
            if existing is None:
                admin.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN {}").format(
                        sql.Identifier(role),
                        sql.SQL(
                            "BYPASSRLS" if role == "service_role" else "NOBYPASSRLS"
                        ),
                    )
                )
            elif existing != (False, role == "service_role", False):
                pytest.fail(
                    f"Unexpected existing role attributes for {role}; use an isolated cluster"
                )

        admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(isolated_name))
        )
        try:
            with psycopg.connect(isolated_dsn, autocommit=True) as setup:
                setup.execute("CREATE SCHEMA auth")
                setup.execute(
                    "CREATE TABLE auth.users (id uuid PRIMARY KEY, email text)"
                )
                setup.execute(
                    (MIGRATIONS / "0001_digital_hr.sql").read_text(encoding="utf-8")
                )
                for name, person_id in people.items():
                    role = (
                        "hr_admin"
                        if name == "hr"
                        else "manager"
                        if name in ("manager", "other_manager")
                        else "worker"
                    )
                    manager_id = (
                        people["manager"]
                        if name == "worker"
                        else people["other_manager"]
                        if name == "outsider"
                        else None
                    )
                    setup.execute(
                        "INSERT INTO auth.users(id, email) VALUES (%s, %s)",
                        (person_id, f"{name}@example.test"),
                    )
                    setup.execute(
                        """INSERT INTO public.employee_profiles(
                            id, auth_user_id, employee_code, full_name, email,
                            company, job_title, department, manager_id, hired_at,
                            vacation_days_remaining, role
                        ) VALUES (%s, %s, %s, %s, %s, 'Test', 'Test', 'Test',
                                  %s, '2025-01-01', 24, %s)""",
                        (
                            person_id,
                            person_id,
                            name,
                            name,
                            f"{name}@example.test",
                            manager_id,
                            role,
                        ),
                    )
                for status, request_id in legacy.items():
                    reviewed = status != "pending"
                    setup.execute(
                        """INSERT INTO public.hr_requests(
                            id, employee_id, request_type, status, start_date, end_date,
                            comment, reviewed_by, reviewer_comment, reviewed_at,
                            created_at
                        ) VALUES (%s, %s, 'leave', %s, '2026-10-01', '2026-10-02',
                                  'Legacy request', %s, %s, %s, '2026-09-01 10:00:00+00')""",
                        (
                            request_id,
                            people["worker"],
                            status,
                            people["manager"] if reviewed else None,
                            "Legacy decision" if reviewed else None,
                            "2026-09-02 10:00:00+00" if reviewed else None,
                        ),
                    )
                migrations = sorted(MIGRATIONS.glob("0002*.sql"))
                assert len(migrations) == 1, (
                    "Expected exactly one request workflow migration"
                )
                setup.execute(migrations[0].read_text(encoding="utf-8"))
                setup.execute("GRANT USAGE ON SCHEMA public TO anon, authenticated")
                setup.execute(
                    """CREATE FUNCTION public.test_fail_notification() RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    BEGIN
                        IF current_setting('posttech_test.fail_notifications', true) = 'on' THEN
                            RAISE EXCEPTION 'Forced notification failure' USING ERRCODE = 'P0001';
                        END IF;
                        RETURN NEW;
                    END;
                    $$;
                    CREATE TRIGGER test_fail_notification BEFORE INSERT ON public.notifications
                    FOR EACH ROW EXECUTE FUNCTION public.test_fail_notification();"""
                )
            yield WorkflowDatabase(isolated_dsn, people, legacy)
        finally:
            # This identifier is generated here, never provided by the environment.
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(isolated_name)
                )
            )


def test_leave_create_review_history_and_notifications(db):
    with db.connect() as connection:
        created = create_request(connection, db.people["worker"])
        assert created["status"] == "pending"
        assert created["employee_id"] == db.people["worker"]
        assert "idempotency_key" not in created
        assert counts(connection, created["id"]) == (1, 1, 1)
        reviewer_notice = connection.execute(
            "SELECT employee_id::text, notification_type FROM public.notifications WHERE request_id = %s",
            (created["id"],),
        ).fetchone()
        assert reviewer_notice == (db.people["manager"], "request_created")

        reviewed = review_request(
            connection, db.people["manager"], created["id"], comment="Согласовано"
        )
        assert reviewed["status"] == "approved"
        assert reviewed["reviewed_by"] == db.people["manager"]
        assert reviewed["reviewer_comment"] == "Согласовано"
        assert reviewed["reviewed_at"]
        assert counts(connection, created["id"]) == (1, 2, 2)
        history = connection.execute(
            """SELECT actor_id::text, event_type, from_status::text, to_status::text, comment
               FROM public.request_events WHERE request_id = %s ORDER BY created_at, id""",
            (created["id"],),
        ).fetchall()
        assert history == [
            (db.people["worker"], "created", None, "pending", DEFAULT_LEAVE["comment"]),
            (db.people["manager"], "approved", "pending", "approved", "Согласовано"),
        ]
        worker_notice = connection.execute(
            """SELECT employee_id::text FROM public.notifications
               WHERE request_id = %s AND notification_type = 'request_status_changed'""",
            (created["id"],),
        ).fetchall()
        assert worker_notice == [(db.people["worker"],)]


def test_same_creation_key_replays_without_duplicate_events_or_notifications(db):
    with db.connect() as connection:
        key = str(uuid4())
        first = create_request(connection, db.people["worker"], key)
        second = create_request(connection, db.people["worker"], key)
        assert second == first
        assert counts(connection, first["id"]) == (1, 1, 1)


def test_creation_retry_after_review_returns_current_request(db):
    with db.connect() as connection:
        key = str(uuid4())
        created = create_request(connection, db.people["worker"], key)
        reviewed = review_request(connection, db.people["manager"], created["id"])
        replay = create_request(connection, db.people["worker"], key)
        assert replay == reviewed
        assert counts(connection, created["id"]) == (1, 2, 2)


@pytest.mark.parametrize("changed", [{"comment": "Other"}, {"end_date": "2026-11-07"}])
def test_same_creation_key_with_different_payload_conflicts(db, changed):
    with db.connect() as connection:
        key = str(uuid4())
        created = create_request(connection, db.people["worker"], key)
        with sqlstate("PT409"):
            create_request(connection, db.people["worker"], key, **changed)
        assert counts(connection, created["id"]) == (1, 1, 1)


def test_creation_key_is_scoped_to_employee(db):
    with db.connect() as connection:
        key = str(uuid4())
        first = create_request(connection, db.people["worker"], key)
        second = create_request(connection, db.people["outsider"], key)
        assert first["id"] != second["id"]


def test_identical_review_replays_and_conflicting_review_fails(db):
    with db.connect() as connection:
        created = create_request(connection, db.people["worker"])
        reviewed = review_request(
            connection,
            db.people["manager"],
            created["id"],
            "rejected",
            "Нужны другие даты",
        )
        assert (
            review_request(
                connection,
                db.people["manager"],
                created["id"],
                "rejected",
                "Нужны другие даты",
            )
            == reviewed
        )
        for actor, status, comment in (
            (db.people["manager"], "approved", "Нужны другие даты"),
            (db.people["manager"], "rejected", "Изменённый комментарий"),
            (db.people["hr"], "rejected", "Нужны другие даты"),
        ):
            with sqlstate("PT409"):
                review_request(connection, actor, created["id"], status, comment)
        assert counts(connection, created["id"]) == (1, 2, 2)


def test_create_rolls_back_when_notification_fails_then_retry_succeeds(db):
    with db.connect() as connection:
        key = str(uuid4())
        before = connection.execute(
            "SELECT (SELECT count(*) FROM public.hr_requests), (SELECT count(*) FROM public.request_events)"
        ).fetchone()
        connection.execute("SET posttech_test.fail_notifications = 'on'")
        with sqlstate("P0001"):
            create_request(connection, db.people["worker"], key)
        after = connection.execute(
            "SELECT (SELECT count(*) FROM public.hr_requests), (SELECT count(*) FROM public.request_events)"
        ).fetchone()
        assert before == after
        connection.execute("SET posttech_test.fail_notifications = 'off'")
        created = create_request(connection, db.people["worker"], key)
        assert counts(connection, created["id"]) == (1, 1, 1)


def test_review_rolls_back_when_notification_fails_then_retry_succeeds(db):
    with db.connect() as connection:
        created = create_request(connection, db.people["worker"])
        connection.execute("SET posttech_test.fail_notifications = 'on'")
        with sqlstate("P0001"):
            review_request(connection, db.people["manager"], created["id"])
        unchanged = connection.execute(
            "SELECT status::text, reviewed_by, reviewed_at FROM public.hr_requests WHERE id = %s",
            (created["id"],),
        ).fetchone()
        assert unchanged == ("pending", None, None)
        assert counts(connection, created["id"]) == (1, 1, 1)
        connection.execute("SET posttech_test.fail_notifications = 'off'")
        assert (
            review_request(connection, db.people["manager"], created["id"])["status"]
            == "approved"
        )
        assert counts(connection, created["id"]) == (1, 2, 2)


def test_concurrent_creation_with_same_key_creates_one_request(db):
    barrier = Barrier(2)
    key = str(uuid4())

    def submit():
        with db.connect() as connection:
            barrier.wait(timeout=10)
            return create_request(connection, db.people["worker"], key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: submit(), range(2)))
    assert first == second
    with db.connect() as connection:
        assert counts(connection, first["id"]) == (1, 1, 1)


def test_concurrent_competing_reviews_apply_one_decision(db):
    import psycopg

    with db.connect() as connection:
        created = create_request(connection, db.people["worker"])
    barrier = Barrier(2)

    def decide(actor_status):
        with db.connect() as connection:
            barrier.wait(timeout=10)
            try:
                return review_request(
                    connection, actor_status[0], created["id"], actor_status[1]
                )
            except psycopg.Error as error:
                return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                decide,
                [(db.people["manager"], "approved"), (db.people["hr"], "rejected")],
            )
        )
    winners = [result for result in results if isinstance(result, dict)]
    assert len(winners) == 1
    assert results.count("PT409") == 1
    with db.connect() as connection:
        assert counts(connection, created["id"]) == (1, 2, 2)
        saved = connection.execute(
            "SELECT status::text, reviewed_by::text FROM public.hr_requests WHERE id = %s",
            (created["id"],),
        ).fetchone()
        assert saved == (winners[0]["status"], winners[0]["reviewed_by"])


@pytest.mark.parametrize(
    "actor,owner",
    [
        ("worker", "worker"),
        ("outsider", "worker"),
        ("other_manager", "worker"),
        ("manager", "manager"),
        ("hr", "hr"),
    ],
)
def test_unauthorized_or_self_review_is_forbidden(db, actor, owner):
    with db.connect() as connection:
        created = create_request(connection, db.people[owner])
        before = counts(connection, created["id"])
        with sqlstate("PT403"):
            review_request(connection, db.people[actor], created["id"])
        assert counts(connection, created["id"]) == before
        assert connection.execute(
            "SELECT status::text FROM public.hr_requests WHERE id = %s",
            (created["id"],),
        ).fetchone() == ("pending",)


def test_hr_can_review_outside_manager_team_and_receives_orphan_request(db):
    with db.connect() as connection:
        created = create_request(connection, db.people["orphan"])
        recipients = connection.execute(
            "SELECT employee_id::text FROM public.notifications WHERE request_id = %s",
            (created["id"],),
        ).fetchall()
        assert recipients == [(db.people["hr"],)]
        reviewed = review_request(connection, db.people["hr"], created["id"])
        assert reviewed["status"] == "approved"
        assert reviewed["reviewed_by"] == db.people["hr"]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_client_roles_cannot_execute_mutation_functions(db, role):
    with db.connect(role) as connection:
        with sqlstate("42501"):
            create_request(connection, db.people["worker"])
        with sqlstate("42501"):
            review_request(connection, db.people["manager"], db.legacy["pending"])


def test_functions_are_invoker_and_event_history_is_protected_by_rls(db):
    with db.connect(None) as connection:
        assert connection.execute(
            """SELECT proname, prosecdef FROM pg_proc JOIN pg_namespace n ON n.oid = pronamespace
               WHERE n.nspname = 'public' AND proname IN ('create_hr_request', 'review_hr_request')
               ORDER BY proname"""
        ).fetchall() == [("create_hr_request", False), ("review_hr_request", False)]
        assert connection.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.request_events'::regclass"
        ).fetchone() == (True,)


@pytest.mark.parametrize(
    "changed",
    [
        {"start_date": None},
        {"end_date": "2026-10-01"},
        {"amount": 100},
        {"comment": "x" * 2001},
        {"key": None},
        {"request_type": "advance", "amount": -1, "start_date": None, "end_date": None},
        {
            "request_type": "advance",
            "amount": "25.001",
            "start_date": None,
            "end_date": None,
        },
    ],
)
def test_sql_rejects_invalid_payload_even_without_api_validation(db, changed):
    with db.connect() as connection:
        with sqlstate("PT422"):
            create_request(connection, db.people["worker"], **changed)


def test_unknown_actor_and_unknown_request_are_rejected(db):
    with db.connect() as connection:
        with sqlstate("PT404"):
            create_request(connection, str(uuid4()))
        with sqlstate("PT404"):
            review_request(connection, db.people["manager"], str(uuid4()))


@pytest.mark.parametrize("status", ["pending", "cancelled", None])
def test_review_rejects_unsupported_transition(db, status):
    with db.connect() as connection:
        created = create_request(connection, db.people["worker"])
        with sqlstate("PT422"):
            review_request(connection, db.people["manager"], created["id"], status)
        assert counts(connection, created["id"]) == (1, 1, 1)


def test_empty_review_comment_replays_null_without_another_event(db):
    with db.connect() as connection:
        created = create_request(connection, db.people["worker"])
        reviewed = review_request(
            connection, db.people["manager"], created["id"], comment=None
        )
        assert (
            review_request(connection, db.people["manager"], created["id"], comment="")
            == reviewed
        )
        assert counts(connection, created["id"]) == (1, 2, 2)


def test_advance_request_still_uses_same_workflow(db):
    with db.connect() as connection:
        created = create_request(
            connection,
            db.people["worker"],
            request_type="advance",
            amount="25000.50",
            start_date=None,
            end_date=None,
        )
        assert created["amount"] == 25000.5
        assert created["start_date"] is None
        reviewed = review_request(connection, db.people["manager"], created["id"])
        assert reviewed["status"] == "approved"
        assert counts(connection, created["id"]) == (1, 2, 2)


@pytest.mark.parametrize("status", ["pending", "approved", "rejected"])
def test_migration_backfills_existing_request_history_without_notifications(db, status):
    with db.connect() as connection:
        request_id = db.legacy[status]
        events = connection.execute(
            """SELECT event_type, actor_id::text, from_status::text, to_status::text,
                      comment, created_at::text
               FROM public.request_events WHERE request_id = %s ORDER BY created_at, id""",
            (request_id,),
        ).fetchall()
        assert events[0][:5] == (
            "created",
            db.people["worker"],
            None,
            "pending",
            "Legacy request",
        )
        assert events[0][5].startswith("2026-09-01 10:00:00")
        if status == "pending":
            assert len(events) == 1
        else:
            assert len(events) == 2
            assert events[1][:5] == (
                status,
                db.people["manager"],
                "pending",
                status,
                "Legacy decision",
            )
            assert events[1][5].startswith("2026-09-02 10:00:00")
        assert counts(connection, request_id)[2] == 0


def test_demo_seed_can_be_applied_twice_with_complete_history(db):
    import psycopg

    seed = (MIGRATIONS.parent / "seed.sql").read_text(encoding="utf-8")
    with db.connect(None) as connection:
        original_profiles = connection.execute(
            "SELECT count(*) FROM public.employee_profiles"
        ).fetchone()[0]
        # Keep the additional HR account and demo data out of other scenarios.
        with connection.transaction():
            for email in (
                "hr@posttech.demo",
                "manager@posttech.demo",
                "employee@posttech.demo",
            ):
                connection.execute(
                    "INSERT INTO auth.users(id, email) VALUES (%s, %s)",
                    (str(uuid4()), email),
                )
            connection.execute(seed)
            first_requests = connection.execute(
                """SELECT r.id::text FROM public.hr_requests r
                   JOIN public.employee_profiles e ON e.id = r.employee_id
                   WHERE e.email = 'employee@posttech.demo' ORDER BY r.id"""
            ).fetchall()
            connection.execute(seed)

            employee = connection.execute(
                """SELECT e.id, e.manager_id, m.id, e.role::text, m.role::text
                   FROM public.employee_profiles e
                   JOIN public.employee_profiles m ON m.id = e.manager_id
                   WHERE e.email = 'employee@posttech.demo'
                     AND m.email = 'manager@posttech.demo'"""
            ).fetchone()
            assert employee is not None
            employee_id, manager_id, linked_manager_id, employee_role, manager_role = (
                employee
            )
            assert manager_id == linked_manager_id
            assert (employee_role, manager_role) == ("worker", "manager")
            assert connection.execute(
                "SELECT role::text FROM public.employee_profiles WHERE email = 'hr@posttech.demo'"
            ).fetchone() == ("hr_admin",)
            assert (
                connection.execute(
                    "SELECT id::text FROM public.hr_requests WHERE employee_id = %s ORDER BY id",
                    (employee_id,),
                ).fetchall()
                == first_requests
            )
            assert len(first_requests) == 2
            assert connection.execute(
                """SELECT request_type::text, status::text, reviewed_by
                   FROM public.hr_requests WHERE employee_id = %s ORDER BY request_type::text""",
                (employee_id,),
            ).fetchall() == [
                ("advance", "approved", manager_id),
                ("leave", "pending", None),
            ]
            assert connection.execute(
                """SELECT r.request_type::text, e.event_type, count(*)
                   FROM public.request_events e
                   JOIN public.hr_requests r ON r.id = e.request_id
                   WHERE r.employee_id = %s
                   GROUP BY r.request_type, e.event_type ORDER BY r.request_type::text, e.event_type""",
                (employee_id,),
            ).fetchall() == [
                ("advance", "approved", 1),
                ("advance", "created", 1),
                ("leave", "created", 1),
            ]
            assert connection.execute(
                "SELECT count(*) FROM public.course_assignments WHERE employee_id = %s",
                (employee_id,),
            ).fetchone() == (2,)
            assert connection.execute(
                "SELECT count(*) FROM public.notifications WHERE employee_id = %s",
                (employee_id,),
            ).fetchone() == (1,)
            raise psycopg.Rollback
        assert connection.execute(
            "SELECT count(*) FROM public.employee_profiles"
        ).fetchone() == (original_profiles,)
