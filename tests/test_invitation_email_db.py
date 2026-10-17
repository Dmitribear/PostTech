from contextlib import contextmanager
from hashlib import sha256

import pytest

from test_registration_db import invitation_db as base_db, issue
from test_request_workflow_db import DATABASE_URL, MIGRATIONS, sqlstate

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Local PostgreSQL required")


@pytest.fixture
def email_db():
    with contextmanager(base_db.__wrapped__)() as db:
        with db.connect(None) as c:
            c.execute(
                (MIGRATIONS / "0013_invitation_email.sql").read_text(encoding="utf-8")
            )
        yield db


def test_send_rotates_and_preserves_role_and_throttles(email_db):
    db = email_db
    with db.connect() as c:
        old, inv, details = issue(c, db, role="manager")
        digest = sha256(b"new-code").hexdigest()
        args = (db.people["hr"], inv["id"], digest)
        value = c.execute("select begin_invitation_email(%s,%s,%s)", args).fetchone()[0]
        assert value["email"] == details["email"] and value["role"] == "manager"
        with sqlstate("PT404"):
            c.execute("select check_registration_invitation(%s,false)", (old,))
        assert (
            c.execute(
                "select check_registration_invitation(%s,false)", (digest,)
            ).fetchone()[0]["role"]
            == "manager"
        )
        with sqlstate("PT429"):
            c.execute("select begin_invitation_email(%s,%s,%s)", args)
        # Late response for the previous code cannot change the current status.
        assert (
            c.execute(
                "select finish_invitation_email(%s,%s,%s)", (inv["id"], old, "accepted")
            ).fetchone()[0]["recorded"]
            is False
        )
        c.execute(
            "select finish_invitation_email(%s,%s,%s)", (inv["id"], digest, "failed")
        )
        rows = c.execute(
            "select list_registration_invitations(%s)", (db.people["hr"],)
        ).fetchone()[0]
        assert rows[0]["email_status"] == "failed"
        assert "token_hash" not in rows[0]


def test_send_permissions_and_revocation(email_db):
    db = email_db
    with db.connect() as c:
        digest, inv, _ = issue(c, db)
        with sqlstate("PT403"):
            c.execute(
                "select begin_invitation_email(%s,%s,%s)",
                (db.people["manager"], inv["id"], digest),
            )
        c.execute(
            "select revoke_registration_invitation(%s,%s)", (db.people["hr"], inv["id"])
        )
        with sqlstate("PT410"):
            c.execute(
                "select begin_invitation_email(%s,%s,%s)",
                (db.people["hr"], inv["id"], digest),
            )
    for role in ("anon", "authenticated"):
        with db.connect(role) as c:
            with sqlstate("42501"):
                c.execute(
                    "select begin_invitation_email(%s,%s,%s)",
                    (db.people["hr"], inv["id"], digest),
                )
