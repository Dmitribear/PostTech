"""Compile the team migration plan in a disposable local PostgreSQL database.

Set POSTTECH_TEST_DATABASE_URL to an empty posttech_test_* database on the
literal loopback address 127.0.0.1 or ::1. No .env file is read. This command
creates a new UUID database, applies the plan and drops only that database.
Supabase Auth is represented by a minimal local users table, not a live service.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def local_connection_options(dsn: str) -> dict[str, str]:
    from psycopg.conninfo import conninfo_to_dict

    if not dsn:
        raise ValueError("Set POSTTECH_TEST_DATABASE_URL to an empty local test database")
    options = conninfo_to_dict(dsn)
    host = options.get("host")
    if host not in {"127.0.0.1", "::1"} or options.get("service"):
        raise ValueError("Only literal loopback PostgreSQL hosts are allowed; services are forbidden")
    if options.get("hostaddr", host) != host:
        raise ValueError("hostaddr must match the loopback host")
    if not re.fullmatch(r"posttech_test_[A-Za-z0-9_]+", options.get("dbname", "")):
        raise ValueError("The base database name must start with posttech_test_")
    if not options.get("user"):
        raise ValueError("An explicit PostgreSQL user is required")
    if not options.get("port", "").isdigit() or not 1 <= int(options["port"]) <= 65535:
        raise ValueError("An explicit PostgreSQL port is required")
    # Explicit numeric hostaddr also overrides any inherited PGHOSTADDR value.
    return {**options, "hostaddr": host, "connect_timeout": "5"}


def migration_files(repo: Path) -> list[tuple[str, Path]]:
    repo = repo.resolve()
    plan = json.loads((repo / "database/migration-plan.json").read_text(encoding="utf-8"))
    paths = plan.get("migrations")
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise ValueError("The migration plan must contain a nonempty list of paths")
    if len(paths) != len(set(paths)):
        raise ValueError("The migration plan contains duplicate paths")
    result = []
    for relative in paths:
        path = (repo / relative).resolve()
        if not path.is_relative_to(repo / "database/migrations") or path.suffix != ".sql" or not path.is_file():
            raise ValueError(f"Missing or unsafe migration: {relative}")
        result.append((relative, path))
    return result


def check_database(dsn: str, repo: Path = ROOT) -> dict:
    import psycopg
    from psycopg import sql

    options = local_connection_options(dsn)
    files = migration_files(repo)
    isolated_name = "posttech_test_compile_" + uuid4().hex
    report = {"database": isolated_name, "migrations": [], "success": False, "dropped": False}
    with psycopg.connect(**options, autocommit=True) as admin:
        address, port = admin.execute("SELECT inet_server_addr()::text, inet_server_port()").fetchone()
        if not ipaddress.ip_interface(address).ip.is_loopback or port != int(options["port"]):
            raise ValueError("The connection is not to the requested loopback PostgreSQL server")
        tables = admin.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema')"
        ).fetchall()
        if tables:
            raise ValueError("Refusing a nonempty base database; create an empty disposable database")
        # Roles are cluster-wide. Existing roles are checked but never altered.
        for role in ("anon", "authenticated", "service_role"):
            attributes = admin.execute(
                "SELECT rolcanlogin, rolbypassrls, rolsuper FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone()
            if attributes is None:
                admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN {}").format(
                    sql.Identifier(role), sql.SQL("BYPASSRLS" if role == "service_role" else "NOBYPASSRLS")
                ))
            elif attributes != (False, role == "service_role", False):
                raise ValueError(f"Unexpected existing role attributes for {role}; use an isolated cluster")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(isolated_name)))
        try:
            with psycopg.connect(**{**options, "dbname": isolated_name}, autocommit=True) as connection:
                connection.execute("SET statement_timeout = '30s'")
                connection.execute("CREATE SCHEMA auth")
                connection.execute("CREATE TABLE auth.users(id uuid PRIMARY KEY, email text, email_confirmed_at timestamptz)")
                for relative, path in files:
                    connection.execute(path.read_text(encoding="utf-8"))
                    report["migrations"].append(relative)
                report["tables"] = connection.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE'"
                ).fetchone()[0]
                report["success"] = True
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = str(exc)
        finally:
            # Never interpolate the environment's database name into DROP.
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(isolated_name)))
            report["dropped"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = check_database(os.environ.get("POSTTECH_TEST_DATABASE_URL", ""), args.repo)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
