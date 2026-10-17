"""Provision three isolated fictional jury accounts; never reset existing users."""
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
from app.core.config import get_settings
from app.db.supabase import get_supabase_client, _create_client, _secret_value

PEOPLE = {
    "hr": ("hr_admin", None, "Демо HR · Мадина", "HR-администратор"),
    "manager": ("manager", None, "Демо руководитель · Ерлан", "Руководитель хаба"),
    "employee": ("worker", "manager", "Демо сотрудник · Алия", "Оператор хаба"),
}


def provision(project_ref: str):
    settings = get_settings()
    url = str(settings.supabase_url or "").rstrip("/")
    if not re.fullmatch(r"[a-z0-9]{20}", project_ref) or urlparse(url).hostname != f"{project_ref}.supabase.co":
        raise RuntimeError("Project reference mismatch")
    db = get_supabase_client()
    db.table("knowledge_articles").select("id,version,reviewed_at").limit(1).execute()
    checkpoint = ROOT / ".local/jury-credentials.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state.get("project_ref") != project_ref or not re.fullmatch(r"[a-f0-9]{12}", state.get("fixture_id", "")):
            raise RuntimeError("Existing jury checkpoint mismatch")
    else:
        fixture = uuid4().hex[:12]
        state = {"project_ref": project_ref, "fixture_id": fixture}
        for name in PEOPLE:
            state[name] = {"email": f"jury.{name}+{fixture}@posttech.demo", "password": secrets.token_urlsafe(30)}
        save_private(checkpoint, state)
    fixture = state["fixture_id"]
    for name, (role, manager, full_name, job_title) in PEOPLE.items():
        account = state[name]
        expected_email = f"jury.{name}+{fixture}@posttech.demo"
        if account.get("email") != expected_email or not isinstance(account.get("password"), str):
            raise RuntimeError("Unexpected stored identity")
        if account.get("auth_user_id"):
            user = db.auth.admin.get_user_by_id(account["auth_user_id"]).user
        else:
            try:
                user = db.auth.admin.create_user({"email": expected_email, "password": account["password"], "email_confirm": True,
                    "app_metadata": {"posttech_jury_fixture": fixture}}).user
            except Exception:
                public = _create_client(url, _secret_value(settings.supabase_anon_key))
                user = public.auth.sign_in_with_password({"email": expected_email, "password": account["password"]}).user
        if not user or user.email != expected_email or user.app_metadata.get("posttech_jury_fixture") != fixture:
            raise RuntimeError("Account identity mismatch")
        account["auth_user_id"] = str(user.id)
        save_private(checkpoint, state)
        expected = {"auth_user_id": str(user.id), "employee_code": f"JURY-{name.upper()}-{fixture}", "email": expected_email,
                    "role": role, "manager_id": state[manager]["profile_id"] if manager else None, "external_source": "posttech-jury-fixture"}
        found = db.table("employee_profiles").select("*").eq("auth_user_id", str(user.id)).limit(1).execute().data or []
        if found:
            profile = found[0]
            if any(profile.get(k) != v for k, v in expected.items()):
                raise RuntimeError("Existing profile mismatch; no overwrite")
        else:
            profile = db.table("employee_profiles").insert({**expected, "full_name": full_name, "job_title": job_title,
                "company": "PostTech · стенд жюри", "department": "Демонстрационная команда", "hired_at": "2025-01-01", "vacation_days_remaining": 24}).execute().data[0]
        account["profile_id"] = str(profile["id"])
        save_private(checkpoint, state)
    return {"status": "ready", "accounts": len(PEOPLE), "roles": [v[0] for v in PEOPLE.values()], "emails_sent": 0,
            "credentials_file": str(checkpoint)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-ref", required=True)
    try:
        print(json.dumps(provision(p.parse_args().project_ref)))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "message": "Stopped without changing existing accounts. Reuse the same checkpoint."}))
        sys.exit(1)
