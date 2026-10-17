"""Isolated PostgreSQL benchmark, never seeds Supabase or an application database.

Requires POSTTECH_TEST_DATABASE_URL pointing at an EMPTY local posttech_test_* DB.
Creates a random disposable database, runs the real migrations/RPCs, then drops it.
This measures SQL workflows, not HTTP, Auth, AI or external integrations.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta, datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_extensions_db import db as fixture
from test_request_workflow_db import DATABASE_URL, create_request, review_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--employees", type=int, default=150)
    parser.add_argument("--calls", type=int, default=400)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/performance/extensions.json"
    )
    args = parser.parse_args()
    from psycopg.conninfo import conninfo_to_dict

    if DATABASE_URL and conninfo_to_dict(DATABASE_URL).get("host") not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        parser.error("Benchmark must use a local, isolated PostgreSQL server")
    if (
        not DATABASE_URL
        or not 10 <= args.employees <= 1000
        or not 1 <= args.workers <= 32
        or not 20 <= args.calls <= 10000
    ):
        parser.error(
            "Set safe test DSN; employees 10–1000, workers 1–32, calls 20–10000"
        )
    with contextmanager(fixture.__wrapped__)() as database:
        employee_ids = []
        start = date.today() + timedelta(days=60)
        with database.connect(None) as c:
            for i in range(args.employees):
                id = str(uuid4())
                employee_ids.append(id)
                c.execute(
                    "insert into auth.users(id,email) values(%s,%s)",
                    (id, f"scale-{i}@example.test"),
                )
                c.execute(
                    """insert into employee_profiles(id,auth_user_id,employee_code,full_name,email,company,job_title,department,manager_id,hired_at,vacation_days_remaining)
                 values(%s,%s,%s,%s,%s,'Synthetic','Test','Scale',%s,'2025-01-01',30)""",
                    (
                        id,
                        id,
                        f"SCALE-{i}",
                        f"Synthetic employee {i}",
                        f"scale-{i}@example.test",
                        database.people["manager"],
                    ),
                )
        with database.connect() as c:
            for id in employee_ids:
                create_request(
                    c, id, start_date=start, end_date=start + timedelta(days=4)
                )
                r = create_request(
                    c,
                    id,
                    start_date=start + timedelta(days=10),
                    end_date=start + timedelta(days=12),
                )
                review_request(c, database.people["manager"], r["id"])
                create_request(
                    c,
                    id,
                    request_type="advance",
                    start_date=None,
                    end_date=None,
                    amount=5000,
                )

        def run_batch(indices):
            measurements = []
            errors = 0
            with database.connect() as c:
                for i in indices:
                    began = time.perf_counter()
                    try:
                        id = employee_ids[i % len(employee_ids)]
                        if i % 3 == 0:
                            value = c.execute(
                                "select read_leave_balance(%s)", (id,)
                            ).fetchone()[0]
                            assert value["available_days"] == 22
                        elif i % 3 == 1:
                            rows = c.execute(
                                "select id,status from hr_requests where employee_id=%s order by created_at desc limit 20",
                                (id,),
                            ).fetchall()
                            assert len(rows) == 3
                        else:
                            rows = c.execute(
                                "select id from integration_outbox where status='queued' order by next_attempt_at limit 20"
                            ).fetchall()
                            assert rows
                    except Exception:
                        errors += 1
                    measurements.append((time.perf_counter() - began) * 1000)
            return measurements, errors

        began = time.perf_counter()
        with ThreadPoolExecutor(args.workers) as pool:
            batches = list(
                pool.map(
                    run_batch,
                    [range(i, args.calls, args.workers) for i in range(args.workers)],
                )
            )
        elapsed = time.perf_counter() - began
        times = sorted(t for batch, _ in batches for t in batch)
        with database.connect() as c:
            counts = {
                table: c.execute(f"select count(*) from {table}").fetchone()[0]
                for table in ("employee_profiles", "hr_requests", "integration_outbox")
            }
        report = dict(
            measured_at=datetime.now(timezone.utc).isoformat(),
            scope="local PostgreSQL SQL-only; excludes HTTP/Auth/AI/external services",
            counts=counts,
            calls=args.calls,
            workers=args.workers,
            errors=sum(e for _, e in batches),
            elapsed_seconds=round(elapsed, 3),
            operations_per_second=round(args.calls / elapsed, 1),
            median_ms=round(statistics.median(times), 2),
            p95_ms=round(times[max(0, int(len(times) * 0.95) - 1)], 2),
            max_ms=round(max(times), 2),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
