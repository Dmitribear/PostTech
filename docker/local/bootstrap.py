"""Initialize only the dedicated Docker database, after GoTrue's own migrations."""
from pathlib import Path
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

import psycopg

ROOT = Path(__file__).resolve().parents[2]
ACCOUNTS = ("hr@posttech.demo", "director@posttech.demo", "manager@posttech.demo", "employee@posttech.demo")


def transaction_body(source):
    # Each manifest file receives its own transaction and ledger entry. Enum
    # extensions commit before the following migration uses their new values.
    return re.sub(r"(?im)^\s*(?:begin|commit);[ \t]*$", "", source)


def apply_file(connection, relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT / "database") or path.suffix != ".sql":
        raise RuntimeError("Migration path must remain inside database/")
    source = path.read_text(encoding="utf-8-sig")
    checksum = hashlib.sha256(source.encode()).hexdigest()
    previous = connection.execute("SELECT checksum FROM posttech_bootstrap.files WHERE name=%s", (relative,)).fetchone()
    if previous:
        if previous[0] != checksum:
            raise RuntimeError(f"Already applied SQL changed: {relative}; review a forward migration instead of overwriting it")
        return
    with connection.transaction():
        connection.execute(transaction_body(source))
        connection.execute("INSERT INTO posttech_bootstrap.files(name,checksum) VALUES (%s,%s)", (relative, checksum))
    print(f"Applied {relative}", flush=True)


def create_accounts(connection):
    key, password = os.environ["POSTTECH_SERVICE_KEY"], os.environ["POSTTECH_DEMO_PASSWORD"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for email in ACCOUNTS:
        if connection.execute("SELECT 1 FROM auth.users WHERE email=%s", (email,)).fetchone():
            continue
        request = urllib.request.Request("http://auth:9999/admin/users", method="POST", data=json.dumps({
            "email": email, "password": password, "email_confirm": True,
        }).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=30) as response:
                if response.status not in (200, 201):
                    raise RuntimeError("Local Auth refused account creation")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Local Auth could not create a demo account (HTTP {exc.code})") from None
    print("Four local demo identities are ready", flush=True)


def main():
    if os.environ.get("POSTTECH_LOCAL_BOOTSTRAP") != "1":
        raise SystemExit("This initializer is only for the local Docker stack")
    # Deliberately no SUPABASE_URL, DATABASE_URL, CLI DSN or .env loading.
    with psycopg.connect(host="db", port=5432, dbname="posttech_local", user="postgres",
                          password=os.environ["POSTTECH_DB_PASSWORD"], autocommit=True) as connection:
        identity = connection.execute("SELECT current_database(), purpose FROM posttech_bootstrap.identity").fetchone()
        if identity != ("posttech_local", "posttech-local-docker"):
            raise SystemExit("Refusing a database without the local Docker identity")
        connection.execute("SELECT pg_advisory_lock(hashtext('posttech-local-bootstrap'))")
        connection.execute("SET posttech.local_container='on'")
        connection.execute("""CREATE TABLE IF NOT EXISTS posttech_bootstrap.files (
            name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())""")
        applied = connection.execute("SELECT count(*) FROM posttech_bootstrap.files").fetchone()[0]
        if not applied and connection.execute("SELECT to_regclass('public.employee_profiles')").fetchone()[0]:
            raise SystemExit("Existing application schema has no bootstrap ledger; manual review required")
        plan = json.loads((ROOT / "database/migration-plan.json").read_text(encoding="utf-8-sig"))
        for migration in plan["migrations"]:
            apply_file(connection, migration)
        create_accounts(connection)
        apply_file(connection, "database/seed.sql")
        apply_file(connection, "database/seed_local_director.sql")
        apply_file(connection, "database/seed_jana_demo.sql")
        # Auth owns its schema; API service_role needs read access for verified invitations.
        connection.execute("GRANT SELECT ON auth.users TO service_role")
        connection.execute("NOTIFY pgrst, 'reload schema'")
    print("Local Docker data, migrations and Jana knowledge are ready", flush=True)


if __name__ == "__main__":
    main()
