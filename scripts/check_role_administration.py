"""Check role administration on disposable PostgreSQL; requires local Docker.

Run: python -m scripts.check_role_administration
No Supabase credentials are read. No host ports or persistent volumes are used.
"""

import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    container_id = ""
    try:
        container_id = subprocess.check_output(
            ["docker", "run", "--rm", "--detach", "--network", "none",
             "--name", f"posttech-role-tests-{uuid4().hex[:12]}",
             "--mount", "type=tmpfs,destination=/var/lib/postgresql/data",
             "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:16-alpine"],
            text=True,
        ).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise RuntimeError("Docker did not return a valid test container ID")
        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", container_id, "pg_isready", "-U", "postgres"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Test PostgreSQL did not become ready")

        command = ["docker", "exec", "-i", container_id, "psql", "-X", "-q", "-t", "-A",
                   "-U", "postgres", "-v", "ON_ERROR_STOP=1"]

        def sql(statement: str) -> str:
            completed = subprocess.run(command, input=statement, encoding="utf-8", capture_output=True)
            if completed.returncode:
                raise RuntimeError(completed.stderr)
            return completed.stdout.strip()

        sql("""
            create schema auth;
            create table auth.users (id uuid primary key, email text not null);
            create role service_role nologin bypassrls;
            create role anon nologin;
            create role authenticated nologin;
            insert into auth.users values
              (gen_random_uuid(), 'hr@posttech.demo'),
              (gen_random_uuid(), 'director@posttech.demo'),
              (gen_random_uuid(), 'manager@posttech.demo'),
              (gen_random_uuid(), 'employee@posttech.demo');
        """)
        for migration in sorted((ROOT / "database/migrations").glob("*.sql")):
            sql(migration.read_text(encoding="utf-8"))
        sql((ROOT / "database/seed.sql").read_text(encoding="utf-8"))
        # Replaying additive migrations must keep the schema usable.
        sql((ROOT / "database/migrations/0004_hr_role_administration.sql").read_text(encoding="utf-8"))
        sql((ROOT / "database/migrations/0005_vacation_balance.sql").read_text(encoding="utf-8"))
        print(sql((ROOT / "database/tests/role_administration.sql").read_text(encoding="utf-8")))
        print(sql((ROOT / "database/tests/vacation_balance.sql").read_text(encoding="utf-8")))

        # Two HR administrators attempt to demote each other concurrently.
        sql("""
            grant usage on schema public to service_role;
            grant select, update on public.employee_profiles to service_role;
            update public.employee_profiles set role = 'hr_admin' where email = 'employee@posttech.demo';
        """)
        admin_id = sql("select id from employee_profiles where email = 'hr@posttech.demo';")
        other_id = sql("select id from employee_profiles where email = 'employee@posttech.demo';")
        processes = []
        for actor_id, target_id in [(admin_id, other_id), (other_id, admin_id)]:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, encoding="utf-8")
            process.stdin.write(
                f"begin; set local role service_role; "
                f"select * from public.assign_employee_role('{actor_id}', '{target_id}', 'worker'); "
                "select pg_sleep(0.2); commit;"
            )
            process.stdin.close()
            process.stdin = None
            processes.append(process)
        results = [(process, process.communicate(timeout=30)) for process in processes]
        assert sorted(process.returncode for process, _ in results) == [0, 3], results
        assert any("HR administrator role required" in output[1] for _, output in results), results
        assert sql("select count(*) from employee_profiles where role = 'hr_admin';") == "1"
        assert sql("select count(*) from employee_role_changes;") == "1"
        print("Concurrent mutual demotion passed: exactly one HR administrator remains")
        sql((ROOT / "database/migrations/0004_hr_role_administration.sql").read_text(encoding="utf-8"))
        assert sql("select count(*) from employee_profiles where role = 'hr_admin';") == "1"
        assert sql("select count(*) from employee_role_changes;") == "1"
        print("Migration replay preserved assigned roles and their audit history")
    finally:
        if re.fullmatch(r"[0-9a-f]{64}", container_id):
            subprocess.run(["docker", "rm", "--force", "--volumes", container_id],
                           check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
