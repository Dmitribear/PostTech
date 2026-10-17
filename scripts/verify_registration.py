"""Opt-in registration verification on real Supabase, without sending emails.

Creates only new fictional @posttech.demo fixtures. Supabase admin.generate_link
generates the confirmation OTP locally; it does not deliver mail. Existing
accounts and passwords are never reset. Secrets remain in Git-ignored files.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client
from app.application.use_cases.invitations import code_hash
from provision_live_accounts import save_private
from verify_live_workflow import (
    API,
    VerificationError,
    checkpoint_lock,
    ignored_path,
    now,
    read_json,
    require,
)


class RegistrationCheck:
    def __init__(self, args):
        self.args = args
        self.stage = "setup"
        self.api = API(args.base_url)
        self.path = ignored_path(args.fixture)
        self.report_path = ignored_path(args.report)
        self.accounts = read_json(ignored_path(args.credentials))
        self.project_ref = args.project_ref
        require(
            urlsplit(str(get_settings().supabase_url)).hostname
            == self.project_ref + ".supabase.co",
            "Selected project does not match local configuration",
        )
        require(
            self.accounts.get("project_ref") == self.project_ref,
            "Scenario credentials belong to another project",
        )
        self.state = read_json(self.path) if self.path.exists() else {}
        if not self.state:
            fixture_id = uuid4().hex
            self.state = {
                "project_ref": self.project_ref,
                "fixture_id": fixture_id,
                "email": f"registration.{fixture_id}@posttech.demo",
                "password": "R9-" + secrets.token_urlsafe(30),
                "checks": {},
                "api_calls": 0,
            }
            self.save()
        require(
            self.state.get("project_ref") == self.project_ref,
            "Registration fixture belongs to another project",
        )
        require(
            self.state.get("email")
            == f"registration.{self.state['fixture_id']}@posttech.demo",
            "Registration fixture is not an expected fictional account",
        )
        self.admin = get_supabase_client()

    def save(self):
        self.state["last_stage"] = self.stage
        self.state["updated_at"] = now()
        save_private(self.path, self.state)

    def flag(self, name):
        self.state["checks"][name] = True
        self.save()

    def call(self, method, path, actor=None, body=None, expected=200):
        return self.api.call(method, path, actor, body, expected)

    def run(self):
        self.stage = "fixture_identity"
        for actor, role in (("hr", "hr_admin"), ("employee", "worker")):
            account = self.accounts[actor]
            require(
                account["email"].endswith("@posttech.demo"),
                "Only fictional scenario accounts are permitted",
            )
            session = self.call(
                "POST",
                "/auth/login",
                body={"email": account["email"], "password": account["password"]},
            )
            require(
                session["user_id"] == account["auth_user_id"],
                "Scenario Auth identity mismatch",
            )
            self.api.tokens[actor] = session["access_token"]
            profile = self.call("GET", "/profile", actor)
            require(
                profile["id"] == account["profile_id"]
                and profile["role"] == role
                and profile.get("external_source") == "posttech-scenario-check",
                "Scenario profile identity mismatch",
            )
        self.flag("existing_fixture_identity_verified")
        fixture = self.state["fixture_id"]
        details = {
            "email": self.state["email"],
            "employee_code": "REGISTRATION-" + fixture,
            "company": "PostTech · демонстрационная проверка",
            "job_title": "Тестовый сотрудник",
            "department": "Проверка регистрации",
            "hired_at": str(date.today() + timedelta(days=1)),
            "manager_id": self.accounts["manager"]["profile_id"],
            "role": "worker",
            "vacation_days_remaining": 24,
            "expires_in_hours": 72,
        }

        self.stage = "issuer_authorization"
        self.call("POST", "/auth/invitations", "employee", details, 403)
        self.call("GET", "/auth/invitations", "employee", expected=403)
        self.call("POST", "/auth/invitations", body=details, expected=401)
        self.flag("invitation_management_requires_hr")

        self.stage = "invitation_issue"
        if "invitation" not in self.state:
            # An interrupted response cannot reveal a lost code again. Revoke
            # only this unique fixture's unused invitation, then issue a new one.
            listing = self.call("GET", "/auth/invitations", "hr")
            for invite in listing:
                if invite["email"] == self.state["email"] and not invite["revoked_at"]:
                    require(
                        not invite["consumed_at"],
                        "A consumed fixture exists without its local checkpoint",
                    )
                    self.call("POST", f"/auth/invitations/{invite['id']}/revoke", "hr")
            self.state["invitation"] = self.call(
                "POST", "/auth/invitations", "hr", details, 201
            )
            self.save()
        invite = self.state["invitation"]
        code = invite["invitation_code"]
        listing = self.call("GET", "/auth/invitations", "hr")
        require(
            all(
                "token_hash" not in row and "invitation_code" not in row
                for row in listing
            ),
            "Invitation listing exposes a secret",
        )
        self.flag("hr_issue_and_list_without_secret_disclosure")
        self.call(
            "POST",
            "/auth/invitations/check",
            body={"invitation_code": "JP-invalid-" + fixture},
            expected=404,
        )
        self.flag("unknown_invitation_rejected")

        if not self.state["checks"].get("real_email_otp_confirmed"):
            checked = self.call(
                "POST", "/auth/invitations/check", body={"invitation_code": code}
            )
            require(
                checked["email"] == details["email"] and checked["role"] == "worker",
                "Invitation identity changed",
            )
            # Invalid schema guarantees the mail-sending registration handler
            # cannot run. No valid /register or /resend request is made here.
            self.call(
                "POST",
                "/auth/register",
                body={
                    "invitation_code": code,
                    "first_name": "Проверка",
                    "last_name": "Регистрации",
                    "password": "weak",
                    "role": "hr_admin",
                },
                expected=422,
            )
            self.flag("weak_password_blocked_before_mail")
            self.stage = "prepare_names_without_mail"
            if not self.state.get("prepared"):
                self.admin.rpc(
                    "prepare_registration_invitation",
                    {
                        "p_token_hash": code_hash(code),
                        "p_first_name": "Проверка",
                        "p_last_name": "Регистрации",
                        "p_resend": False,
                    },
                ).execute()
                self.state["prepared"] = True
                self.save()
            self.stage = "generate_otp_without_mail"
            if not self.state.get("email_otp"):
                generated = self.admin.auth.admin.generate_link(
                    {
                        "type": "signup",
                        "email": self.state["email"],
                        "password": self.state["password"],
                        "options": {"data": {"posttech_registration_check": fixture}},
                    }
                )
                require(
                    generated.user.email == self.state["email"],
                    "Generated Auth account has unexpected email",
                )
                self.state["auth_user_id"] = str(generated.user.id)
                self.state["email_otp"] = generated.properties.email_otp
                require(
                    isinstance(self.state["email_otp"], str)
                    and self.state["email_otp"].isdigit(),
                    "Auth did not return a numeric OTP",
                )
                self.save()
            self.stage = "verify_real_otp"
            correct = self.state["email_otp"]
            wrong = ("0" if correct[0] != "0" else "1") + correct[1:]
            self.call(
                "POST",
                "/auth/verify-registration",
                body={"invitation_code": code, "token": wrong},
                expected=400,
            )
            self.flag("wrong_email_otp_rejected")
            session = self.call(
                "POST",
                "/auth/verify-registration",
                body={
                    "invitation_code": code,
                    "token": correct,
                    "email": "other@posttech.demo",
                    "role": "hr_admin",
                },
            )
            require(
                session["user_id"] == self.state["auth_user_id"],
                "Verified Auth identity mismatch",
            )
            self.api.tokens["new"] = session["access_token"]
            self.state.pop("email_otp", None)
            self.flag("real_email_otp_confirmed")

        self.stage = "password_login_and_profile"
        session = self.call(
            "POST",
            "/auth/login",
            body={"email": self.state["email"], "password": self.state["password"]},
        )
        require(
            session["user_id"] == self.state["auth_user_id"],
            "Password sign-in changed Auth identity",
        )
        self.api.tokens["new"] = session["access_token"]
        profile = self.call("GET", "/profile", "new")
        require(
            profile["role"] == "worker"
            and profile["email"] == self.state["email"]
            and profile["employee_code"] == details["employee_code"]
            and profile["manager_id"] == details["manager_id"]
            and profile["vacation_days_remaining"] == 24
            and profile["external_source"] == "hr-invitation",
            "Activated profile differs from HR invitation",
        )
        self.state["profile_id"] = profile["id"]
        self.flag("password_login_and_invitation_bound_worker_profile")
        self.call(
            "POST",
            "/auth/invitations/check",
            body={"invitation_code": code},
            expected=409,
        )
        self.flag("consumed_invitation_rejected")
        self.call(
            "POST",
            "/auth/complete-invitation",
            body={
                "invitation_code": code,
                "email": "other@posttech.demo",
                "password": self.state["password"],
            },
            expected=403,
        )
        recovered = self.call(
            "POST",
            "/auth/complete-invitation",
            body={
                "invitation_code": code,
                "email": self.state["email"],
                "password": self.state["password"],
                "first_name": "Попытка",
                "last_name": "Изменения",
                "role": "hr_admin",
            },
        )
        require(
            recovered["user_id"] == self.state["auth_user_id"],
            "Idempotent completion changed user",
        )
        self.api.tokens["new"] = recovered["access_token"]
        repeated = self.call("GET", "/profile", "new")
        require(
            repeated["id"] == profile["id"]
            and repeated["role"] == "worker"
            and repeated["full_name"] == profile["full_name"],
            "Idempotent completion changed profile name or role",
        )
        self.flag("same_user_completion_idempotent_and_role_immutable")

        self.stage = "revoked_invitation"
        if "revoked_invitation" not in self.state:
            revoked_details = {
                **details,
                "email": f"registration.revoked.{fixture}@posttech.demo",
                "employee_code": "REGISTRATION-REVOKED-" + fixture,
            }
            self.state["revoked_invitation"] = self.call(
                "POST", "/auth/invitations", "hr", revoked_details, 201
            )
            self.save()
        revoked = self.state["revoked_invitation"]
        self.call(
            "POST",
            f"/auth/invitations/{revoked['id']}/revoke",
            "employee",
            expected=403,
        )
        self.call("POST", f"/auth/invitations/{revoked['id']}/revoke", "hr")
        self.call(
            "POST",
            "/auth/invitations/check",
            body={"invitation_code": revoked["invitation_code"]},
            expected=410,
        )
        self.flag("revoked_invitation_rejected")
        self.stage = "complete"
        self.state["api_calls"] += self.api.calls
        self.save()
        report = {
            "status": "passed",
            "verified_at": now(),
            "project_ref": self.project_ref,
            "api_call_count": self.api.calls,
            "cumulative_api_call_count": self.state["api_calls"],
            "new_auth_accounts": 1,
            "invitations_created": 2,
            "emails_sent": 0,
            "email_delivery_verified": False,
            "checks": self.state["checks"],
        }
        save_private(self.report_path, report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly permit fictional live fixtures; never sends emails",
    )
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--credentials", default=".local/scenario-credentials.json")
    parser.add_argument("--fixture", default=".local/registration-credentials.json")
    parser.add_argument("--report", default=".local/registration-verification.json")
    args = parser.parse_args()
    if not args.live:
        parser.error(
            "Use --live to explicitly permit creation of fictional live fixtures"
        )
    suite = None
    try:
        fixture_path = ignored_path(args.fixture)
        with checkpoint_lock(fixture_path):
            suite = RegistrationCheck(args)
            result = suite.run()
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except VerificationError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": suite.stage if suite else "setup",
                    "error": str(exc),
                }
            )
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": suite.stage if suite else "setup",
                    "error_type": type(exc).__name__,
                    "error": "Registration check stopped; keep the private checkpoint for recovery. No secret diagnostics emitted",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
