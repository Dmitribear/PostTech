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
