"""Full team migration plan and cross-branch business rules in disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
import json
from pathlib import Path
from uuid import uuid4

import pytest

from test_request_workflow_db import (
    DATABASE_URL, db as legacy_db, sqlstate, create_request, review_request,
)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Set a local POSTTECH_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def team_db():
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(DATABASE_URL)
    if options.get("host") not in ("127.0.0.1", "::1", "localhost") or not options.get("dbname", "").startswith("posttech_test_"):
        pytest.fail("Team tests require a loopback posttech_test_* database")
    with contextmanager(legacy_db.__wrapped__)() as database:
        with database.connect(None) as connection:
            connection.execute("ALTER TABLE auth.users ADD COLUMN email_confirmed_at timestamptz DEFAULT now()")
            plan = json.loads((ROOT / "database/migration-plan.json").read_text(encoding="utf-8"))
            applied = {"database/migrations/0001_digital_hr.sql", "database/migrations/0002_request_workflow.sql"}
            for relative in plan["migrations"]:
                if relative not in applied:
                    connection.execute((ROOT / relative).read_text(encoding="utf-8"))
        yield database


def add_person(connection, role="worker", manager_id=None, balance=24):
    person = str(uuid4())
    connection.execute("INSERT INTO auth.users(id,email) VALUES (%s,%s)", (person, f"{person}@example.test"))
    connection.execute("""INSERT INTO employee_profiles
        (id,auth_user_id,employee_code,full_name,email,company,job_title,department,manager_id,hired_at,vacation_days_remaining,role)
        VALUES (%s,%s,%s,%s,%s,'Test','Test','Test',%s,'2025-01-01',%s,%s)""",
        (person, person, person, role, f"{person}@example.test", manager_id, balance, role))
    return person


@pytest.fixture
def people(team_db):
    with team_db.connect(None) as c:
        director = add_person(c, "director")
        manager = add_person(c, "manager", director)
        return {
            "hr": add_person(c, "hr_admin"), "director": director, "manager": manager,
            "worker": add_person(c, manager_id=manager), "outsider": add_person(c),
            "deputy": add_person(c, "director"),
        }


def leave(c, owner, offset=90, days=5):
    start = date.today() + timedelta(days=offset)
    return create_request(c, owner, start_date=start, end_date=start + timedelta(days=days - 1))


def balance(c, owner):
    return c.execute("SELECT read_leave_balance(%s)", (owner,)).fetchone()[0]


@pytest.mark.parametrize("supervisor", ["manager", "director"])
def test_two_stages_debit_once_and_preserve_reserve(team_db, people, supervisor):
    p = people
    with team_db.connect(None) as c:
        worker = add_person(c, manager_id=p[supervisor])
    with team_db.connect() as c:
        req = leave(c, worker)
        assert balance(c, worker)["available_days"] == 19
        with sqlstate("PT409"):
            review_request(c, p["hr"], req["id"])
        first = review_request(c, p[supervisor], req["id"], comment="Согласовано")
        assert first["status"] == "pending_hr"
        assert balance(c, worker)["official_days"] == 24
        assert balance(c, worker)["pending_days"] == 5
        assert balance(c, worker)["available_days"] == 19
        assert c.execute("SELECT count(*) FROM integration_outbox WHERE aggregate_id=%s", (req["id"],)).fetchone()[0] == 0
        with sqlstate("PT409"):
            leave(c, worker)
        final = review_request(c, p["hr"], req["id"], comment="HR approved")
        assert final["status"] == "approved"
        assert final[f"{supervisor}_reviewed_by"] == p[supervisor]
        assert final["hr_reviewed_by"] == p["hr"]
        for _ in range(2):
            review_request(c, p["hr"], req["id"], comment="HR approved")
            review_request(c, p[supervisor], req["id"], comment="Согласовано")
        assert balance(c, worker)["official_days"] == 19
        assert balance(c, worker)["available_days"] == 19
        assert balance(c, worker)["pending_days"] == 0
        assert balance(c, worker)["approved_unreconciled_days"] == 0
        assert c.execute("SELECT state FROM leave_holds WHERE request_id=%s", (req["id"],)).fetchone()[0] == "reconciled"
        assert c.execute("SELECT count(*) FROM integration_outbox WHERE aggregate_id=%s", (req["id"],)).fetchone()[0] == 2
        assert [r[0] for r in c.execute("SELECT event_type FROM request_events WHERE request_id=%s ORDER BY created_at,id", (req["id"],))] == ["created", "pending_hr", "approved"]
        with sqlstate("PT409"):
            c.execute("SELECT cancel_hr_request(%s,%s)", (worker, req["id"]))


@pytest.mark.parametrize("after_supervisor", [False, True])
def test_owner_cancellation_releases_without_debit(team_db, people, after_supervisor):
    with team_db.connect() as c:
        req = leave(c, people["worker"])
        if after_supervisor:
            review_request(c, people["manager"], req["id"])
        for _ in range(2):
            result = c.execute("SELECT cancel_hr_request(%s,%s)", (people["worker"], req["id"])).fetchone()[0]
            assert result["status"] == "cancelled"
        assert balance(c, people["worker"])["available_days"] == 24
        assert balance(c, people["worker"])["official_days"] == 24
        assert c.execute("SELECT state FROM leave_holds WHERE request_id=%s", (req["id"],)).fetchone()[0] == "released"


def test_hr_rejection_and_failed_notification_roll_back_final_debit(team_db, people):
    with team_db.connect() as c:
        req = leave(c, people["worker"])
        review_request(c, people["manager"], req["id"])
        c.execute("SET posttech_test.fail_notifications='on'")
        try:
            with sqlstate("P0001"):
                review_request(c, people["hr"], req["id"])
        finally:
            c.execute("SET posttech_test.fail_notifications='off'")
        assert balance(c, people["worker"])["official_days"] == 24
        assert balance(c, people["worker"])["pending_days"] == 5
        assert c.execute("SELECT status FROM hr_requests WHERE id=%s", (req["id"],)).fetchone()[0] == "pending_hr"
        assert c.execute("SELECT count(*) FROM integration_outbox WHERE aggregate_id=%s", (req["id"],)).fetchone()[0] == 0
        review_request(c, people["hr"], req["id"], status="rejected", comment="Не согласовано")
        assert balance(c, people["worker"])["available_days"] == 24


def test_orphan_routes_directly_to_hr_and_never_self_approves(team_db, people):
    with team_db.connect() as c:
        req = leave(c, people["outsider"])
        assert req["approval_route"] == "hr"
        assert review_request(c, people["hr"], req["id"])["status"] == "approved"
        own = leave(c, people["hr"])
        with sqlstate("PT403"):
            review_request(c, people["hr"], own["id"])


def test_director_delegation_first_stage_only(team_db, people):
    p = people
    with team_db.connect() as c:
        c.execute("SELECT manage_approval_delegation(%s,%s,%s,%s,%s,%s,%s)",
            (p["hr"], str(uuid4()), p["manager"], p["deputy"], date.today(), date.today()+timedelta(days=3), "Замещение"))
        req = leave(c, p["worker"])
        assert review_request(c, p["deputy"], req["id"])["status"] == "pending_hr"
        event = c.execute("SELECT delegation_id FROM request_events WHERE request_id=%s AND event_type='pending_hr'", (req["id"],)).fetchone()
        assert event[0]
        with sqlstate("PT409"):
            review_request(c, p["manager"], req["id"])
        assert review_request(c, p["hr"], req["id"])["status"] == "approved"


def test_hr_cannot_be_assigned_ambiguous_first_stage_delegation(team_db, people):
    with team_db.connect() as c:
        for manager, deputy in ((people["manager"], people["hr"]), (people["hr"], people["director"])):
            with sqlstate("PT422"):
                c.execute("SELECT manage_approval_delegation(%s,%s,%s,%s,%s,%s,%s)",
                    (people["hr"], str(uuid4()), manager, deputy, date.today(), date.today()+timedelta(days=3), "Неоднозначная роль"))


def test_concurrent_final_approval_is_one_debit(team_db, people):
    with team_db.connect() as c:
        req = leave(c, people["worker"])
        review_request(c, people["manager"], req["id"])
    def approve(_):
        with team_db.connect() as c:
            return review_request(c, people["hr"], req["id"])["status"]
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(approve, [0, 1])) == ["approved", "approved"]
    with team_db.connect() as c:
        assert balance(c, people["worker"])["official_days"] == 19
        assert c.execute("SELECT count(*) FROM request_events WHERE request_id=%s AND event_type='approved'", (req["id"],)).fetchone()[0] == 1


def test_role_administration_keeps_director_and_audit(team_db, people):
    with team_db.connect() as c:
        c.execute("SELECT * FROM assign_employee_role(%s,%s,'director')", (people["hr"], people["outsider"]))
        assert c.execute("SELECT role FROM employee_profiles WHERE id=%s", (people["outsider"],)).fetchone()[0] == "director"
        assert c.execute("SELECT count(*) FROM employee_role_changes WHERE employee_id=%s", (people["outsider"],)).fetchone()[0] == 1
        with sqlstate("PT409"):
            c.execute("SELECT * FROM assign_employee_role(%s,%s,'worker')", (people["hr"], people["hr"]))


def test_browser_cannot_invoke_server_rpc(team_db, people):
    with team_db.connect("authenticated") as c:
        with sqlstate("42501"):
            c.execute("SELECT get_hr_request_routing(%s)", (people["worker"],))


def test_balance_reconciliation_cannot_erase_pending_reservations(team_db, people):
    with team_db.connect() as c:
        leave(c, people["worker"], days=10)
        with sqlstate("PT409"):
            c.execute("SELECT reconcile_leave_balance(%s,%s,%s,5,'{}'::uuid[],%s)",
                (people["hr"], str(uuid4()), people["worker"], "Unverified low snapshot"))
        assert balance(c, people["worker"])["official_days"] == 24


def test_combined_demo_seed_is_repeatable_with_real_two_stage_history(team_db):
    seed = (ROOT / "database/seed.sql").read_text(encoding="utf-8")
    with team_db.connect(None) as c:
        for name in ("hr", "director", "manager", "employee"):
            c.execute("INSERT INTO auth.users(id,email) VALUES (%s,%s)", (str(uuid4()), f"{name}@posttech.demo"))
        c.execute(seed)
        first = c.execute("SELECT count(*) FROM notifications").fetchone()[0]
        c.execute(seed)
        assert c.execute("SELECT count(*) FROM notifications").fetchone()[0] == first
        request = c.execute("""SELECT r.id,r.status,e.role FROM hr_requests r
            JOIN employee_profiles p ON p.id=r.employee_id
            JOIN employee_profiles e ON e.id=r.reviewed_by
            WHERE p.email='employee@posttech.demo' AND request_type='advance'""").fetchone()
        assert request[1:] == ("approved", "hr_admin")
        assert c.execute("SELECT count(*) FROM request_events WHERE request_id=%s", (request[0],)).fetchone()[0] == 3
        assert c.execute("""SELECT manager.role FROM employee_profiles worker JOIN employee_profiles manager ON manager.id=worker.manager_id
            WHERE worker.email='manager@posttech.demo'""").fetchone()[0] == "director"


def test_director_academy_assignment_deadline_and_passing_score(team_db, people):
    from psycopg.types.json import Jsonb
    course = str(uuid4())
    with team_db.connect(None) as c:
        c.execute("""INSERT INTO courses(id,title,description,material_markdown,quiz,passing_score)
            VALUES (%s,'Course','Demo','Read the material',%s,80)""",
            (course, Jsonb([{"id": "q1", "prompt": "Question", "options": ["A", "B"], "answer_index": 1}])))
    with team_db.connect() as c:
        assignment = c.execute("SELECT assign_academy_course_due(%s,%s,%s,%s)",
            (people["director"], people["manager"], course, date.today()+timedelta(days=10))).fetchone()[0]
        assert assignment["due_on"]
        with sqlstate("PT403"):
            c.execute("SELECT assign_academy_course(%s,%s,%s)", (people["director"], people["outsider"], course))
        c.execute("SELECT update_academy_progress(%s,%s,90)", (people["manager"], course))
        failed = c.execute("SELECT submit_academy_quiz(%s,%s,%s,%s)",
            (people["manager"], course, Jsonb({"q1": 0}), str(uuid4()))).fetchone()[0]
        assert failed["status"] == "in_progress" and failed["progress_percent"] == 90
        passed = c.execute("SELECT submit_academy_quiz(%s,%s,%s,%s)",
            (people["manager"], course, Jsonb({"q1": 1}), str(uuid4()))).fetchone()[0]
        assert passed["status"] == "completed" and passed["progress_percent"] == 100
        assert c.execute("SELECT count(*) FROM notifications WHERE employee_id=%s AND course_id=%s AND notification_type='team_course_completed'",
            (people["director"], course)).fetchone()[0] == 1


def test_invitation_accepts_director_reporting_line_and_immutable_role(team_db, people):
    from hashlib import sha256
    from psycopg.types.json import Jsonb
    token = sha256(uuid4().bytes).hexdigest()
    user = str(uuid4())
    email = f"{user}@invitation.example.test"
    details = {"email": email, "employee_code": user, "company": "Demo", "job_title": "Demo",
        "department": "Demo", "hired_at": "2026-01-01", "manager_id": people["director"],
        "role": "manager", "vacation_days_remaining": 18, "expires_in_hours": 72}
    with team_db.connect(None) as c:
        c.execute("INSERT INTO auth.users(id,email,email_confirmed_at) VALUES (%s,%s,now())", (user, email))
    with team_db.connect() as c:
        c.execute("SELECT issue_registration_invitation(%s,%s,%s)", (people["hr"], token, Jsonb(details)))
        c.execute("SELECT prepare_registration_invitation(%s,'Test','Manager',false)", (token,))
        result = c.execute("SELECT complete_registration_invitation(%s,%s)", (token, user)).fetchone()[0]
        row = c.execute("SELECT manager_id::text,role,vacation_days_remaining FROM employee_profiles WHERE id=%s", (result["profile_id"],)).fetchone()
        assert row == (people["director"], "manager", 18)
