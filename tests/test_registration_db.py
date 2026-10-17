"""Invitation invariants on real, disposable PostgreSQL databases."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import pytest

from test_request_workflow_db import DATABASE_URL, MIGRATIONS, db as legacy_db, sqlstate

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Set POSTTECH_TEST_DATABASE_URL for real PostgreSQL tests")


@pytest.fixture
def invitation_db():
    with contextmanager(legacy_db.__wrapped__)() as database:
        with database.connect(None) as connection:
            connection.execute("ALTER TABLE auth.users ADD COLUMN email_confirmed_at timestamptz")
            connection.execute((MIGRATIONS / "0005_registration_invitations.sql").read_text(encoding="utf-8"))
        yield database


def issue(connection, db, **changes):
    from psycopg.types.json import Jsonb
    token = sha256(uuid4().bytes).hexdigest()
    details = {"email": f"new-{uuid4().hex}@example.test", "employee_code": uuid4().hex,
        "company": "PostTech", "job_title": "Test", "department": "Logistics", "hired_at": "2026-10-16",
        "manager_id": db.people["manager"], "role": "worker", "vacation_days_remaining": 24,
        "expires_in_hours": 72, **changes}
    result = connection.execute("SELECT public.issue_registration_invitation(%s,%s,%s)", (db.people["hr"], token, Jsonb(details))).fetchone()[0]
    return token, result, details


def prepare(connection, token, resend=False):
    return connection.execute("SELECT public.prepare_registration_invitation(%s,%s,%s,%s)",
        (token, None if resend else "Алексей", None if resend else "Ким", resend)).fetchone()[0]


def complete(connection, token, user_id):
    return connection.execute("SELECT public.complete_registration_invitation(%s,%s)", (token, user_id)).fetchone()[0]


def add_user(db, email, confirmed=True):
    user_id = str(uuid4())
    with db.connect(None) as connection:
        connection.execute("INSERT INTO auth.users(id,email,email_confirmed_at) VALUES(%s,%s,CASE WHEN %s THEN now() END)", (user_id,email,confirmed))
    return user_id


def test_invitation_immutable_authority_and_idempotency(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, issued, details = issue(connection,db,role="manager",vacation_days_remaining=18.5)
        assert "token_hash" not in issued and "invitation_code" not in issued
        prepare(connection,token)
        user = add_user(db,details["email"])
        result = complete(connection,token,user)
        assert result["role"] == "manager"
        assert complete(connection,token,user) == result
    with db.connect(None) as connection:
        row = connection.execute("SELECT auth_user_id::text,full_name,role::text,vacation_days_remaining,manager_id::text FROM public.employee_profiles WHERE id=%s", (result["profile_id"],)).fetchone()
        assert row == (user,"Алексей Ким","manager",18.5,db.people["manager"])
        connection.execute("UPDATE public.registration_invitations SET expires_at=now()-interval '1 hour',created_at=now()-interval '2 hours' WHERE id=%s",(issued["id"],))
        assert connection.execute("SELECT expires_at<clock_timestamp() FROM public.registration_invitations WHERE id=%s",(issued["id"],)).fetchone() == (True,)
    with db.connect() as connection:
        assert complete(connection,token,user) == result
        with sqlstate("PT409"):
            connection.execute("SELECT public.check_registration_invitation(%s,false)",(token,))


def test_unconfirmed_or_wrong_email_cannot_consume_invitation(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, _, details = issue(connection,db)
        prepare(connection,token)
        unconfirmed = add_user(db,details["email"],False)
        other = add_user(db,"other@example.test",True)
        for user in (unconfirmed,other):
            with sqlstate("PT403"):
                complete(connection,token,user)
    with db.connect(None) as connection:
        assert connection.execute("SELECT consumed_at,profile_id FROM public.registration_invitations WHERE token_hash=%s",(token,)).fetchone() == (None,None)
        connection.execute("UPDATE auth.users SET email_confirmed_at=now() WHERE id=%s",(unconfirmed,))
    with db.connect() as connection:
        assert complete(connection,token,unconfirmed)["profile_id"]


def test_expired_and_revoked_invitations_fail_before_profile_creation(invitation_db):
    db = invitation_db
    for kind in ("expired","revoked"):
        with db.connect() as connection:
            token, issued, details = issue(connection,db)
            prepare(connection,token)
            user = add_user(db,details["email"])
            if kind == "revoked":
                connection.execute("SELECT public.revoke_registration_invitation(%s,%s)",(db.people["hr"],issued["id"]))
        if kind == "expired":
            with db.connect(None) as connection:
                connection.execute("UPDATE public.registration_invitations SET created_at=now()-interval '2 hours',expires_at=now()-interval '1 hour' WHERE id=%s",(issued["id"],))
        with db.connect() as connection:
            with sqlstate("PT410"):
                complete(connection,token,user)
            with sqlstate("PT410"):
                prepare(connection,token)


def test_resend_throttled_transactionally_and_rejects_before_signup(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, _, _ = issue(connection,db)
        with sqlstate("PT409"):
            prepare(connection,token,True)
        prepare(connection,token)
        for resend in (False,True):
            with sqlstate("PT429"):
                prepare(connection,token,resend)
    with db.connect(None) as connection:
        connection.execute("UPDATE public.registration_invitations SET last_sent_at=now()-interval '61 seconds' WHERE token_hash=%s",(token,))
    with db.connect() as connection:
        assert prepare(connection,token,True)["email"]


def test_invitation_rpc_and_rows_denied_to_browser_roles(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, issued, _ = issue(connection,db)
    for role in ("anon","authenticated"):
        with db.connect(role) as connection:
            for sql,args in [
                ("SELECT * FROM public.registration_invitations",()),
                ("SELECT public.check_registration_invitation(%s,false)",(token,)),
                ("SELECT public.complete_registration_invitation(%s,%s)",(token,db.people["worker"])),
                ("SELECT public.revoke_registration_invitation(%s,%s)",(db.people["hr"],issued["id"])),
                ("SELECT public.list_registration_invitations(%s)",(db.people["hr"],))]:
                with sqlstate("42501"):
                    connection.execute(sql,args)
    with db.connect() as connection:
        for person in ("worker","manager"):
            with sqlstate("PT403"):
                connection.execute("SELECT public.list_registration_invitations(%s)",(db.people[person],))
            with sqlstate("PT403"):
                connection.execute("SELECT public.revoke_registration_invitation(%s,%s)",(db.people[person],issued["id"]))


def test_issuer_constraints_and_safe_list(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        with sqlstate("PT422"):
            issue(connection,db,manager_id=db.people["worker"])
        with sqlstate("PT409"):
            issue(connection,db,email="worker@example.test")
        token, issued, details = issue(connection,db)
        with sqlstate("PT409"):
            issue(connection,db,email=details["email"])
        listing = connection.execute("SELECT public.list_registration_invitations(%s)",(db.people["hr"],)).fetchone()[0]
        assert listing[0]["id"] == issued["id"]
        assert "token_hash" not in listing[0] and "invitation_code" not in listing[0]


def test_duplicate_concurrent_completion_creates_one_profile(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, _, details = issue(connection,db)
        prepare(connection,token)
    user = add_user(db,details["email"])
    barrier = Barrier(2)
    def activate(_):
        with db.connect() as connection:
            barrier.wait(timeout=5)
            return complete(connection,token,user)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(activate,range(2)))
    assert results[0] == results[1]
    with db.connect(None) as connection:
        assert connection.execute("SELECT count(*) FROM public.employee_profiles WHERE auth_user_id=%s",(user,)).fetchone() == (1,)


def test_manager_changes_before_activation_require_hr_review(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, _, details = issue(connection,db)
        prepare(connection,token)
    user = add_user(db,details["email"])
    with db.connect(None) as connection:
        connection.execute("UPDATE public.employee_profiles SET role='worker' WHERE id=%s",(db.people["manager"],))
    with db.connect() as connection:
        with sqlstate("PT409"):
            complete(connection,token,user)


def test_existing_profile_is_never_reassigned_by_invitation(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, issued, details = issue(connection,db,role="hr_admin")
        prepare(connection,token)
    with db.connect(None) as connection:
        connection.execute("UPDATE auth.users SET email=%s,email_confirmed_at=now() WHERE id=%s",(details["email"],db.people["worker"]))
    with db.connect() as connection:
        with sqlstate("PT409"):
            complete(connection,token,db.people["worker"])
    with db.connect(None) as connection:
        assert connection.execute("SELECT role::text,vacation_days_remaining FROM public.employee_profiles WHERE id=%s",(db.people["worker"],)).fetchone() == ("worker",24)
        assert connection.execute("SELECT consumed_at FROM public.registration_invitations WHERE id=%s",(issued["id"],)).fetchone() == (None,)


def test_revocation_race_is_atomic_with_completion(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, issued, details = issue(connection,db)
        prepare(connection,token)
    user = add_user(db,details["email"])
    barrier = Barrier(2)
    def race(action):
        import psycopg
        with db.connect() as connection:
            barrier.wait(timeout=5)
            try:
                if action == "activate":
                    return action,complete(connection,token,user)
                return action,connection.execute("SELECT public.revoke_registration_invitation(%s,%s)",(db.people["hr"],issued["id"])).fetchone()[0]
            except psycopg.Error as exc:
                return action,exc.sqlstate
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = dict(executor.map(race,["activate","revoke"]))
    if isinstance(results["activate"],dict):
        assert results["revoke"] == "PT409"
    else:
        assert results["activate"] == "PT410" and results["revoke"]["revoked"]
    with db.connect(None) as connection:
        consumed,revoked = connection.execute("SELECT consumed_at,revoked_at FROM public.registration_invitations WHERE id=%s",(issued["id"],)).fetchone()
        assert (consumed is None) != (revoked is None)


def test_verified_existing_auth_account_can_activate_without_signup_email(invitation_db):
    db = invitation_db
    with db.connect() as connection:
        token, issued, details = issue(connection,db)
    user = add_user(db,details["email"])
    with db.connect() as connection:
        with sqlstate("PT422"):
            complete(connection,token,user)
        result = connection.execute("SELECT public.complete_registration_invitation(%s,%s,%s,%s)",
            (token,user,"Verified","Employee")).fetchone()[0]
        replay = connection.execute("SELECT public.complete_registration_invitation(%s,%s,%s,%s)",
            (token,user,"Changed","Name")).fetchone()[0]
        assert result == replay
    with db.connect(None) as connection:
        assert connection.execute("SELECT full_name,role::text FROM public.employee_profiles WHERE id=%s",(result["profile_id"],)).fetchone() == ("Verified Employee","worker")
        assert connection.execute("SELECT last_sent_at FROM public.registration_invitations WHERE id=%s",(issued["id"],)).fetchone() == (None,)
