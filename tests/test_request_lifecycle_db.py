"""Real PostgreSQL lifecycle tests; only UUID-named disposable test databases.

Uses the existing guarded local test harness, applies 0003 after 0001/0002, and
exercises actual locks/constraints/transaction rollback instead of mocking SQL.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest

from test_request_workflow_db import (
    DATABASE_URL, MIGRATIONS, counts, create_request, db as legacy_db,
    review_request, sqlstate,
)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Set POSTTECH_TEST_DATABASE_URL for real PostgreSQL tests")


@pytest.fixture
def lifecycle_db():
    # A fresh, uniquely named database for each test keeps overlap/routing state
    # independent. The original harness verifies the control DB is not an app DB.
    with contextmanager(legacy_db.__wrapped__)() as database:
        with database.connect(None) as connection:
            connection.execute((MIGRATIONS / "0003_request_lifecycle.sql").read_text(encoding="utf-8"))
        yield database


def route(connection, employee):
    return connection.execute("SELECT public.get_hr_request_routing(%s::uuid)", (employee,)).fetchone()[0]


def cancel(connection, employee, request_id):
    return connection.execute("SELECT public.cancel_hr_request(%s::uuid, %s::uuid)", (employee, request_id)).fetchone()[0]


def advance(connection, employee, **kwargs):
    return create_request(connection, employee, request_type="advance", start_date=None, end_date=None, amount=100, **kwargs)


def leave(connection, employee, start=30, end=34, **kwargs):
    today = connection.execute("SELECT (current_timestamp AT TIME ZONE 'Asia/Qyzylorda')::date").fetchone()[0]
    return create_request(connection, employee, start_date=str(today + timedelta(days=start)), end_date=str(today + timedelta(days=end)), **kwargs)


def add_hr(connection):
    person = str(uuid4())
    connection.execute("INSERT INTO auth.users(id,email) VALUES (%s, 'second-hr@example.test')", (person,))
    connection.execute("""INSERT INTO public.employee_profiles(
        id,auth_user_id,employee_code,full_name,email,company,job_title,department,hired_at,role
    ) VALUES (%s,%s,%s,'Second HR','second-hr@example.test','Test','HR','HR','2025-01-01','hr_admin')""", (person, person, person))
    return person


def test_seed_after_lifecycle_has_reviewable_snapshots_and_leaves_other_rows_alone(lifecycle_db):
    db = lifecycle_db
    seed = (MIGRATIONS.parent / "seed.sql").read_text(encoding="utf-8")
    with db.connect(None) as admin:
        for email in ("hr@posttech.demo", "manager@posttech.demo", "employee@posttech.demo"):
            admin.execute("INSERT INTO auth.users(id,email) VALUES (%s,%s)", (str(uuid4()), email))
        admin.execute(seed)
        employee, manager = admin.execute("SELECT id::text,manager_id::text FROM public.employee_profiles WHERE email='employee@posttech.demo'").fetchone()
        seeded = admin.execute("SELECT id::text,request_type::text,approval_route,approvers,approver_ids::text[] FROM public.hr_requests WHERE employee_id=%s ORDER BY request_type::text", (employee,)).fetchall()
        assert len(seeded) == 2
        assert all(row[2] == "manager" and row[4] == [manager] and row[3][0]["id"] == manager for row in seeded)
        unrelated = str(uuid4())
        wrong_employee = str(uuid4())
        admin.execute("INSERT INTO public.hr_requests(id,employee_id,request_type,amount,comment) VALUES (%s,%s,'advance',100,'Ordinary request')", (unrelated, employee))
        admin.execute("INSERT INTO public.hr_requests(id,employee_id,request_type,start_date,end_date,comment) VALUES (%s,%s,'leave',current_date+200,current_date+201,'Демо-заявка на отпуск: ожидает решения руководителя.')", (wrong_employee, db.people["outsider"]))
        admin.execute(seed)
        assert admin.execute("SELECT id::text,request_type::text,approval_route,approvers,approver_ids::text[] FROM public.hr_requests WHERE employee_id=%s AND id<>%s ORDER BY request_type::text", (employee, unrelated)).fetchall() == seeded
        assert admin.execute("SELECT approval_route,approvers,approver_ids FROM public.hr_requests WHERE id IN (%s,%s)", (unrelated, wrong_employee)).fetchall() == [("unassigned", [], []), ("unassigned", [], [])]
        assert admin.execute("SELECT count(*) FROM public.request_events WHERE request_id IN (%s,%s)", (seeded[0][0], seeded[1][0])).fetchone() == (3,)
    with db.connect() as connection:
        leave_id = next(row[0] for row in seeded if row[1] == "leave")
        assert review_request(connection, manager, leave_id)["status"] == "approved"


def test_routing_is_explicit_and_manager_own_goes_to_hr(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        worker = route(connection, db.people["worker"])
        manager = route(connection, db.people["manager"])
        assert worker["route"] == "manager" and worker["can_submit"]
        assert worker["approvers"] == [{"id": db.people["manager"], "full_name": "manager", "role": "manager"}]
        assert manager["route"] == "hr" and manager["can_submit"]
        assert [person["id"] for person in manager["approvers"]] == [db.people["hr"]]
        created = advance(connection, db.people["manager"])
        assert created["approvers"] == manager["approvers"]
        assert created["approval_route"] == "hr"
        assert "approver_ids" not in created and "idempotency_key" not in created
        assert connection.execute("SELECT employee_id::text FROM public.notifications WHERE request_id=%s", (created["id"],)).fetchall() == [(db.people["hr"],)]
        with sqlstate("PT403"):
            review_request(connection, db.people["manager"], created["id"])
        assert review_request(connection, db.people["hr"], created["id"])["status"] == "approved"


def test_higher_manager_receives_manager_and_hr_own_requests(lifecycle_db):
    db = lifecycle_db
    with db.connect(None) as admin:
        admin.execute("UPDATE public.employee_profiles SET manager_id=%s WHERE id IN (%s,%s)", (db.people["other_manager"], db.people["manager"], db.people["hr"]))
    with db.connect() as connection:
        for employee in ("manager", "hr"):
            created = advance(connection, db.people[employee])
            assert created["approval_route"] == "manager"
            assert [person["id"] for person in created["approvers"]] == [db.people["other_manager"]]
            with sqlstate("PT403"):
                review_request(connection, db.people[employee], created["id"])
            assert review_request(connection, db.people["other_manager"], created["id"])["status"] == "approved"


def test_lone_hr_cannot_submit_to_self_and_failed_create_has_no_side_effects(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        preview = route(connection, db.people["hr"])
        assert preview["can_submit"] is False
        assert preview["route"] == "unassigned" and preview["approvers"] == []
        before = connection.execute("SELECT (SELECT count(*) FROM public.hr_requests), (SELECT count(*) FROM public.request_events), (SELECT count(*) FROM public.notifications)").fetchone()
        with sqlstate("PT409"):
            advance(connection, db.people["hr"])
        assert connection.execute("SELECT (SELECT count(*) FROM public.hr_requests), (SELECT count(*) FROM public.request_events), (SELECT count(*) FROM public.notifications)").fetchone() == before


def test_hr_own_routes_only_to_other_hr(lifecycle_db):
    db = lifecycle_db
    with db.connect(None) as admin:
        second_hr = add_hr(admin)
    with db.connect() as connection:
        created = advance(connection, db.people["hr"])
        assert [person["id"] for person in created["approvers"]] == [second_hr]
        assert connection.execute("SELECT employee_id::text FROM public.notifications WHERE request_id=%s", (created["id"],)).fetchall() == [(second_hr,)]
        assert review_request(connection, second_hr, created["id"])["status"] == "approved"


@pytest.mark.parametrize("invalid_manager", ["worker", "self", "cycle"])
def test_invalid_reporting_chain_falls_back_to_hr(lifecycle_db, invalid_manager):
    db = lifecycle_db
    with db.connect(None) as admin:
        target = db.people["worker"] if invalid_manager == "worker" else db.people["manager"] if invalid_manager == "self" else db.people["other_manager"]
        admin.execute("UPDATE public.employee_profiles SET manager_id=%s WHERE id=%s", (target, db.people["manager"]))
        if invalid_manager == "cycle":
            admin.execute("UPDATE public.employee_profiles SET manager_id=%s WHERE id=%s", (db.people["manager"], db.people["other_manager"]))
    with db.connect() as connection:
        assert route(connection, db.people["manager"])["route"] == "hr"
        assert advance(connection, db.people["manager"])["approvers"][0]["id"] == db.people["hr"]


def test_approver_snapshot_survives_reporting_reassignment(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        created = advance(connection, db.people["worker"])
    with db.connect(None) as admin:
        admin.execute("UPDATE public.employee_profiles SET manager_id=%s WHERE id=%s", (db.people["other_manager"], db.people["worker"]))
        admin.execute("UPDATE public.employee_profiles SET full_name='Renamed manager' WHERE id=%s", (db.people["manager"],))
    with db.connect() as connection:
        assert route(connection, db.people["worker"])["approvers"][0]["id"] == db.people["other_manager"]
        with sqlstate("PT403"):
            review_request(connection, db.people["other_manager"], created["id"])
        reviewed = review_request(connection, db.people["manager"], created["id"])
        assert reviewed["approvers"] == created["approvers"]
        assert reviewed["approvers"][0]["full_name"] == "manager"


def test_any_current_hr_can_triage_other_requests(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        created = advance(connection, db.people["worker"])
        assert created["approvers"][0]["id"] != db.people["hr"]
        assert review_request(connection, db.people["hr"], created["id"])["status"] == "approved"


def test_owner_cancellation_is_atomic_idempotent_and_notifies_owner_and_approver(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        created = leave(connection, db.people["worker"])
        first = cancel(connection, db.people["worker"], created["id"])
        assert first["status"] == "cancelled" and first["cancelled_at"]
        assert first["reviewed_by"] is None and first["reviewed_at"] is None
        assert cancel(connection, db.people["worker"], created["id"]) == first
        assert counts(connection, created["id"]) == (1, 2, 3)
        event = connection.execute("SELECT actor_id::text,from_status::text,to_status::text FROM public.request_events WHERE request_id=%s AND event_type='cancelled'", (created["id"],)).fetchone()
        assert event == (db.people["worker"], "pending", "cancelled")
        recipients = connection.execute("SELECT employee_id::text FROM public.notifications WHERE request_id=%s AND notification_type='request_cancelled'", (created["id"],)).fetchall()
        assert {person[0] for person in recipients} == {db.people["worker"], db.people["manager"]}
        with sqlstate("PT409"):
            review_request(connection, db.people["manager"], created["id"])


@pytest.mark.parametrize("actor", ["outsider", "manager", "hr"])
def test_other_people_cannot_cancel_even_if_hr(lifecycle_db, actor):
    db = lifecycle_db
    with db.connect() as connection:
        created = advance(connection, db.people["worker"])
        with sqlstate("PT403"):
            cancel(connection, db.people[actor], created["id"])
        assert counts(connection, created["id"]) == (1, 1, 1)
        cancel(connection, db.people["worker"], created["id"])
        with sqlstate("PT403"):
            cancel(connection, db.people[actor], created["id"])


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_cancel_cannot_rewrite_a_decision(lifecycle_db, status):
    db = lifecycle_db
    with db.connect() as connection:
        created = advance(connection, db.people["worker"])
        review_request(connection, db.people["manager"], created["id"], status, "Reason")
        with sqlstate("PT409"):
            cancel(connection, db.people["worker"], created["id"])
        assert counts(connection, created["id"]) == (1, 2, 2)


@pytest.mark.parametrize("reason", [None, "", "  \n\t "])
def test_rejection_requires_a_reason_at_sql_boundary(lifecycle_db, reason):
    db = lifecycle_db
    with db.connect() as connection:
        created = advance(connection, db.people["worker"])
        with sqlstate("PT422"):
            review_request(connection, db.people["manager"], created["id"], "rejected", reason)
        assert counts(connection, created["id"]) == (1, 1, 1)


def test_past_leave_rejected_but_today_allowed(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        with sqlstate("PT422"):
            leave(connection, db.people["worker"], -1, 3)
        assert leave(connection, db.people["worker"], 0, 0)["status"] == "pending"


@pytest.mark.parametrize(("start", "end"), [(30, 34), (31, 32), (29, 35), (34, 38), (27, 30)])
def test_active_leave_overlap_is_inclusive(lifecycle_db, start, end):
    db = lifecycle_db
    with db.connect() as connection:
        existing = leave(connection, db.people["worker"])
        with sqlstate("PT409"):
            leave(connection, db.people["worker"], start, end)
        review_request(connection, db.people["manager"], existing["id"])
        with sqlstate("PT409"):
            leave(connection, db.people["worker"], start, end)
        assert leave(connection, db.people["worker"], 35, 35)["id"] != existing["id"]
        assert leave(connection, db.people["outsider"], start, end)["employee_id"] == db.people["outsider"]


@pytest.mark.parametrize("terminal", ["cancelled", "rejected"])
def test_cancelled_and_rejected_leave_no_longer_reserve_dates(lifecycle_db, terminal):
    db = lifecycle_db
    with db.connect() as connection:
        first = leave(connection, db.people["worker"])
        if terminal == "cancelled": cancel(connection, db.people["worker"], first["id"])
        else: review_request(connection, db.people["manager"], first["id"], "rejected", "Other plans")
        assert leave(connection, db.people["worker"])["id"] != first["id"]


def test_retry_is_checked_before_changed_routing_date_and_overlap_policy(lifecycle_db):
    db = lifecycle_db
    key = str(uuid4())
    with db.connect() as connection:
        created = leave(connection, db.people["worker"], key=key)
        assert leave(connection, db.people["worker"], key=key) == created
        cancelled = cancel(connection, db.people["worker"], created["id"])
        assert leave(connection, db.people["worker"], key=key) == cancelled
    # Represent a previously submitted date after its date has passed. Retrying
    # a recorded key acknowledges that row even if no reviewer now exists.
    with db.connect(None) as admin:
        today = admin.execute("SELECT (current_timestamp AT TIME ZONE 'Asia/Qyzylorda')::date").fetchone()[0]
        past = str(today - timedelta(days=10))
        admin.execute("UPDATE public.hr_requests SET start_date=%s,end_date=%s WHERE id=%s", (past, past, created["id"]))
        admin.execute("UPDATE public.employee_profiles SET manager_id=NULL WHERE id=%s", (db.people["worker"],))
        admin.execute("UPDATE public.employee_profiles SET role='worker' WHERE role='hr_admin'")
    with db.connect() as connection:
        replay = create_request(connection, db.people["worker"], key=key, start_date=past, end_date=past)
        assert replay["id"] == created["id"] and replay["status"] == "cancelled"
        with sqlstate("PT409"):
            create_request(connection, db.people["worker"], key=key, start_date=past, end_date=past, comment="Changed")
        assert counts(connection, created["id"]) == (1, 2, 3)


@pytest.mark.parametrize("same_key", [True, False])
def test_simultaneous_creates_serialize_owner_across_distinct_keys(lifecycle_db, same_key):
    import psycopg
    db = lifecycle_db
    barrier = Barrier(2)
    key = str(uuid4())
    def submit(index):
        with db.connect() as connection:
            barrier.wait(timeout=10)
            try: return leave(connection, db.people["worker"], key=key if same_key else str(uuid4()))
            except psycopg.Error as error: return error.sqlstate
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, range(2)))
    if same_key:
        assert results[0] == results[1]
    else:
        assert results.count("PT409") == 1
        assert sum(isinstance(result, dict) for result in results) == 1
    request = next(result for result in results if isinstance(result, dict))
    with db.connect() as connection: assert counts(connection, request["id"]) == (1, 1, 1)


def test_cancel_review_race_has_one_terminal_transition(lifecycle_db):
    import psycopg
    db = lifecycle_db
    with db.connect() as connection: created = leave(connection, db.people["worker"])
    barrier = Barrier(2)
    def decide(operation):
        with db.connect() as connection:
            barrier.wait(timeout=10)
            try:
                return cancel(connection, db.people["worker"], created["id"]) if operation == "cancel" else review_request(connection, db.people["manager"], created["id"])
            except psycopg.Error as error: return error.sqlstate
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(decide, ["cancel", "review"]))
    assert results.count("PT409") == 1
    winner = next(result for result in results if isinstance(result, dict))
    with db.connect() as connection:
        assert counts(connection, created["id"]) == (1, 2, 3 if winner["status"] == "cancelled" else 2)


def test_cancellation_rolls_back_on_notification_failure_and_retries_safely(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        created = leave(connection, db.people["worker"])
        connection.execute("SET posttech_test.fail_notifications='on'")
        with sqlstate("P0001"): cancel(connection, db.people["worker"], created["id"])
        assert connection.execute("SELECT status::text,cancelled_at FROM public.hr_requests WHERE id=%s", (created["id"],)).fetchone() == ("pending", None)
        assert counts(connection, created["id"]) == (1, 1, 1)
        connection.execute("SET posttech_test.fail_notifications='off'")
        cancel(connection, db.people["worker"], created["id"])
        assert counts(connection, created["id"]) == (1, 2, 3)


def test_official_leave_balance_remains_read_only(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        before = connection.execute("SELECT vacation_days_remaining FROM public.employee_profiles WHERE id=%s", (db.people["worker"],)).fetchone()
        first = leave(connection, db.people["worker"])
        review_request(connection, db.people["manager"], first["id"])
        second = leave(connection, db.people["worker"], 40, 45)
        cancel(connection, db.people["worker"], second["id"])
        assert connection.execute("SELECT vacation_days_remaining FROM public.employee_profiles WHERE id=%s", (db.people["worker"],)).fetchone() == before


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_execute_lifecycle_functions(lifecycle_db, role):
    db = lifecycle_db
    with db.connect(role) as connection:
        with sqlstate("42501"): route(connection, db.people["worker"])
        with sqlstate("42501"): cancel(connection, db.people["worker"], db.legacy["pending"])
        with sqlstate("42501"): advance(connection, db.people["worker"])
        with sqlstate("42501"): review_request(connection, db.people["manager"], db.legacy["pending"])


def test_pending_legacy_snapshot_is_backfilled_without_new_events_or_notices(lifecycle_db):
    db = lifecycle_db
    with db.connect() as connection:
        row = connection.execute("SELECT approval_route,approver_ids,approvers FROM public.hr_requests WHERE id=%s", (db.legacy["pending"],)).fetchone()
        assert row[0] == "manager"
        assert str(row[1][0]) == db.people["manager"]
        assert row[2][0]["id"] == db.people["manager"]
        assert counts(connection, db.legacy["pending"]) == (1, 1, 0)
