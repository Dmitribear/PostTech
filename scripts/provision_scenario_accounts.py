"""Create isolated fictional accounts for the full role demonstration.

Never changes an existing password, role, or HR profile. Local credentials are
persisted before creating anything and are intentionally excluded from Git.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from provision_live_accounts import save_private
from app.infrastructure.config import get_settings
from app.infrastructure.database.client import (
    get_supabase_client,
    _create_client,
    _secret_value,
)

# In dependency order; manager remains an employee of the director.
PEOPLE = {
    "hr": ("hr_admin", None, "Демо HR · Мадина", "HR-администратор"),
    "backup_hr": ("hr_admin", None, "Демо HR · Сауле", "Руководитель HR"),
    "director": ("manager", None, "Демо директор · Тимур", "Директор направления"),
    "manager": (
        "manager",
        "director",
        "Демо руководитель · Ерлан",
        "Руководитель хаба",
    ),
    "employee": ("worker", "manager", "Демо сотрудник · Алия", "Оператор хаба"),
    "outsider": (
        "worker",
        "director",
        "Демо другая команда · Дана",
        "Специалист другого хаба",
    ),
    "orphan": ("worker", None, "Демо без руководителя · Арман", "Новый сотрудник"),
}


def provision(project_ref: str) -> dict:
    settings = get_settings()
    url = str(settings.supabase_url or "").rstrip("/")
    if (
        not re.fullmatch(r"[a-z0-9]{20}", project_ref)
        or urlparse(url).hostname != f"{project_ref}.supabase.co"
    ):
        raise RuntimeError("Explicit project reference must match .env")
    client = get_supabase_client()
    path = ROOT / ".local" / "scenario-credentials.json"
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("project_ref") != project_ref or not re.fullmatch(
            r"[a-f0-9]{12}", state.get("fixture_id", "")
        ):
            raise RuntimeError(
                "Existing fixture identity does not match; left unchanged"
            )
    else:
        fixture = uuid4().hex[:12]
        state = {"project_ref": project_ref, "fixture_id": fixture}
        for name in PEOPLE:
            state[name] = {
                "email": f"scenario.{name}+{fixture}@posttech.demo",
                "password": secrets.token_urlsafe(30),
            }
        save_private(path, state)
    fixture = state["fixture_id"]
    result = []
    for name, (role, manager, full_name, job_title) in PEOPLE.items():
        account = state[name]
        expected_email = f"scenario.{name}+{fixture}@posttech.demo"
        if account.get("email") != expected_email or not isinstance(
            account.get("password"), str
        ):
            raise RuntimeError("Fixture account is inconsistent; stopped")
        if account.get("auth_user_id"):
            user = client.auth.admin.get_user_by_id(account["auth_user_id"]).user
        else:
            try:
                user = client.auth.admin.create_user(
                    {
                        "email": expected_email,
                        "password": account["password"],
                        "email_confirm": True,
                        "app_metadata": {"posttech_scenario_check": fixture},
                    }
                ).user
            except Exception:
                # Recovery only with the original password and server-owned marker.
                public = _create_client(url, _secret_value(settings.supabase_anon_key))
                user = public.auth.sign_in_with_password(
                    {"email": expected_email, "password": account["password"]}
                ).user
        if (
            not user
            or user.email != expected_email
            or user.app_metadata.get("posttech_scenario_check") != fixture
        ):
            raise RuntimeError("Account identity mismatch; left unchanged")
        account["auth_user_id"] = str(user.id)
        save_private(path, state)
        expected = {
            "auth_user_id": str(user.id),
            "employee_code": f"SCENARIO-{name.upper()}-{fixture}",
            "email": expected_email,
            "role": role,
            "manager_id": state[manager]["profile_id"] if manager else None,
            "external_source": "posttech-scenario-check",
        }
        found = (
            client.table("employee_profiles")
            .select("*")
            .eq("auth_user_id", str(user.id))
            .limit(1)
            .execute()
            .data
            or []
        )
        if found:
            profile = found[0]
            if any(profile.get(k) != v for k, v in expected.items()):
                raise RuntimeError("Existing profile differs; no overwrite performed")
        else:
            profile = (
                client.table("employee_profiles")
                .insert(
                    {
                        **expected,
                        "full_name": full_name,
                        "job_title": job_title,
                        "company": "PostTech · демонстрация",
                        "department": "HR"
                        if role == "hr_admin"
                        else "Другой хаб"
                        if name == "outsider"
                        else "Тестовый хаб",
                        "hired_at": "2025-01-01",
                        "vacation_days_remaining": 24,
                    }
                )
                .execute()
                .data[0]
            )
        account["profile_id"] = str(profile["id"])
        save_private(path, state)
        result.append({"name": name, "role": role, "profile_id": account["profile_id"]})
    return {"accounts": result, "credentials_file": str(path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-ref", required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                {"status": "ready", **provision(args.project_ref)}, ensure_ascii=True
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": "Stopped without resetting existing accounts. Inspect configuration and rerun with the same local state.",
                }
            )
        )
        raise SystemExit(1)
