"""Opt-in password recovery check on one new fictional Supabase Auth account.

Requires --live and an explicit matching project reference. No emails are sent:
admin.generate_link(type="recovery") creates the OTP, while password changes use
only the PUBLIC /auth/password-reset/confirm endpoint. Existing employee/test
accounts are never selected or modified. A private, ignored checkpoint permits
resuming only this script's own uniquely marked posttech-recovery-check fixture.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.db.supabase import get_supabase_client
from provision_live_accounts import save_private
from verify_live_workflow import API, VerificationError, checkpoint_lock, ignored_path, now, read_json, require


MARKER = "posttech-recovery-check"


class PasswordRecoveryCheck:
    def __init__(self, args):
        self.stage = "setup"
        self.api = API(args.base_url)
        self.path = ignored_path(args.fixture)
        self.report_path = ignored_path(args.report)
        require(self.path != self.report_path, "Credentials and report paths must be different")
        require(re.fullmatch(r"[a-z0-9]{20}", args.project_ref), "Expected a 20-character Supabase project reference")
        selected = urlsplit(str(get_settings().supabase_url))
        require(selected.scheme == "https" and selected.hostname == args.project_ref + ".supabase.co",
                "Selected project does not match local configuration")
        self.project_ref = args.project_ref
        self.state = read_json(self.path) if self.path.exists() else {}
        if not self.state:
            fixture_id = uuid4().hex
            self.state = {"project_ref": self.project_ref, "fixture_id": fixture_id, "source": MARKER,
                "email": f"recovery.{fixture_id}@posttech.demo",
                "original_password": "Original9-" + secrets.token_urlsafe(30),
                "new_password": "Changed9-" + secrets.token_urlsafe(30), "checks": {}, "api_calls": 0}
            self.save()
        require(self.state.get("project_ref") == self.project_ref, "Recovery fixture belongs to another project")
        require(self.state.get("source") == MARKER, "Checkpoint is not a password recovery fixture")
        require(isinstance(self.state.get("fixture_id"), str)
                and re.fullmatch(r"[a-f0-9]{32}", self.state["fixture_id"]), "Recovery fixture identity is invalid")
        require(self.state.get("email") == f"recovery.{self.state['fixture_id']}@posttech.demo",
                "Recovery fixture is not the expected isolated fictional account")
        for field in ("original_password", "new_password"):
            require(isinstance(self.state.get(field), str) and len(self.state[field]) >= 20,
                    "Recovery fixture password is missing or invalid")
        require(self.state["original_password"] != self.state["new_password"], "Recovery fixture passwords must differ")
        require(isinstance(self.state.get("checks"), dict), "Recovery fixture checks are invalid")
        self.admin = get_supabase_client()

    def save(self):
        self.state["last_stage"] = self.stage
        self.state["updated_at"] = now()
        save_private(self.path, self.state)

    def flag(self, name):
        self.state["checks"][name] = True
        self.save()

    def call(self, method, path, body=None, expected=200):
        return self.api.call(method, path, body=body, expected=expected)

    def login(self, password, *, allow_wrong_password=False):
        try:
            response = self.call("POST", "/auth/login", {"email": self.state["email"], "password": password})
        except VerificationError as exc:
            # A transport/provider/rate-limit error must never be treated as an
            # incorrect password when deciding whether a mutation committed.
            if allow_wrong_password and str(exc) == "POST /auth/login returned HTTP 401; expected 200":
                return None
            raise
        require(isinstance(response, dict) and response.get("email") == self.state["email"],
                "Password login returned a different email")
        if self.state.get("auth_user_id"):
            require(response.get("user_id") == self.state["auth_user_id"], "Password login returned a different user")
        return response

    def verify_fixture(self, account):
        require(account is not None and account.email == self.state["email"], "Auth fixture email does not match")
        metadata = getattr(account, "app_metadata", None) or {}
        require(metadata.get("source") == MARKER
                and metadata.get("posttech_recovery_check") == self.state["fixture_id"],
                "Auth account lacks this script's administrative fixture marker; left unchanged")
        require(getattr(account, "email_confirmed_at", None), "Recovery fixture must have a confirmed email")
        if self.state.get("auth_user_id"):
            require(str(account.id) == self.state["auth_user_id"], "Auth fixture identity does not match")

    def run(self):
        self.stage = "endpoint_preflight"
        # Invalid schema cannot consume a token or change a password. This also
        # verifies that the running API includes the new endpoint before setup.
        self.call("POST", "/auth/password-reset/confirm",
                  {"email": self.state["email"], "token": "123456", "password": "weak"}, expected=422)
        self.flag("weak_password_blocked_before_otp")

        self.stage = "new_isolated_auth_fixture"
        if self.state.get("auth_user_id"):
            account = self.admin.auth.admin.get_user_by_id(self.state["auth_user_id"]).user
        else:
            try:
                account = self.admin.auth.admin.create_user({"email": self.state["email"],
                    "password": self.state["original_password"], "email_confirm": True,
                    "app_metadata": {"source": MARKER, "posttech_recovery_check": self.state["fixture_id"]}}).user
            except Exception:
                # Recover a lost create response using the original random
                # password plus an admin-set marker. Never reset by email.
                session = self.login(self.state["original_password"])
                account = self.admin.auth.admin.get_user_by_id(session["user_id"]).user
            self.verify_fixture(account)
            self.state["auth_user_id"] = str(account.id)
            self.save()
        self.verify_fixture(account)
        self.flag("dedicated_fictional_identity_verified")

        # If an earlier process lost the confirm response, establish its result
        # by signing in. Do not blindly reuse a consumed OTP or reset again.
        if self.state.get("mutation_started") and not self.state["checks"].get("public_recovery_password_changed"):
            self.stage = "recover_interrupted_confirmation"
            if self.login(self.state["new_password"], allow_wrong_password=True):
                self.flag("public_recovery_password_changed")

        if not self.state["checks"].get("public_recovery_password_changed"):
            self.stage = "original_password_login"
            original = self.login(self.state["original_password"])
            self.state["prior_refresh_token"] = original["refresh_token"]
            self.flag("original_password_worked_before_reset")

            self.stage = "generate_recovery_otp_without_email"
            # Validate exact identity immediately before issuing a code, even
            # when resuming from an existing local checkpoint.
            self.verify_fixture(self.admin.auth.admin.get_user_by_id(self.state["auth_user_id"]).user)
            generated = self.admin.auth.admin.generate_link({"type": "recovery", "email": self.state["email"]})
            self.verify_fixture(generated.user)
            otp = generated.properties.email_otp
            require(isinstance(otp, str) and re.fullmatch(r"[0-9]{6,8}", otp), "Supabase did not return a numeric recovery OTP")
            self.state["email_otp"] = otp
            self.flag("real_recovery_otp_generated_without_mail")

            self.stage = "wrong_recovery_otp"
            wrong = ("0" if otp[0] != "0" else "1") + otp[1:]
            self.call("POST", "/auth/password-reset/confirm", {"email": self.state["email"], "token": wrong,
                "password": self.state["new_password"]}, expected=400)
            self.flag("wrong_recovery_otp_rejected")

            self.stage = "confirm_public_recovery"
            self.state["mutation_started"] = True
            self.save()
            result = self.call("POST", "/auth/password-reset/confirm", {"email": self.state["email"], "token": otp,
                "password": self.state["new_password"], "role": "hr_admin", "type": "email"})
            require(result == {"message": "Password updated. Sign in with your new password"},
                    "Password recovery returned an unexpected payload or session")
            self.flag("public_recovery_password_changed")
            self.flag("confirmation_returns_no_session")

        self.stage = "reject_recovery_replay"
        if not self.state["checks"].get("consumed_recovery_code_rejected"):
            require(isinstance(self.state.get("email_otp"), str), "Recovery replay checkpoint is missing")
            # A different password avoids a false positive from 'same password'
            # rejection. Subsequent logins independently verify no replay write.
            self.call("POST", "/auth/password-reset/confirm", {"email": self.state["email"],
                "token": self.state["email_otp"], "password": self.state["original_password"]}, expected=400)
            self.flag("consumed_recovery_code_rejected")

        self.stage = "password_login_after_recovery"
        self.call("POST", "/auth/login", {"email": self.state["email"],
                  "password": self.state["original_password"]}, expected=401)
        self.flag("old_password_no_longer_works")
        self.login(self.state["new_password"])
        self.flag("new_password_signs_in_same_identity")

        self.stage = "prior_session_revocation"
        if not self.state["checks"].get("prior_refresh_session_revoked"):
            require(isinstance(self.state.get("prior_refresh_token"), str), "Prior session checkpoint is missing")
            self.call("POST", "/auth/refresh", {"refresh_token": self.state["prior_refresh_token"]}, expected=401)
            self.flag("prior_refresh_session_revoked")

        self.stage = "final_fixture_identity"
        self.verify_fixture(self.admin.auth.admin.get_user_by_id(self.state["auth_user_id"]).user)
        self.flag("fixture_identity_unchanged")
        self.state.pop("email_otp", None)
        self.state.pop("prior_refresh_token", None)
        self.state["api_calls"] += self.api.calls
        self.stage = "complete"
        self.save()
        report = {"status": "passed", "verified_at": now(), "project_ref": self.project_ref,
            "api_call_count": self.api.calls, "cumulative_api_call_count": self.state["api_calls"],
            "fixture_source": MARKER, "dedicated_auth_accounts": 1, "existing_accounts_modified": 0,
            "employee_profiles_created": 0, "emails_sent": 0, "email_delivery_verified": False,
            "checks": self.state["checks"]}
        save_private(self.report_path, report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly permit a new isolated live Auth fixture; sends no emails")
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--fixture", default=".local/recovery-credentials.json")
    parser.add_argument("--report", default=".local/recovery-verification.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live to explicitly permit a new fictional recovery fixture")
    suite = None
    try:
        with checkpoint_lock(ignored_path(args.fixture)):
            suite = PasswordRecoveryCheck(args)
            result = suite.run()
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except VerificationError as exc:
        failure = {"status": "failed", "stage": suite.stage if suite else "setup", "error": str(exc)}
    except Exception as exc:
        failure = {"status": "failed", "stage": suite.stage if suite else "setup", "error_type": type(exc).__name__,
                   "error": "Recovery check stopped; retain the private checkpoint. No secret diagnostics emitted"}
    if suite is not None:
        save_private(suite.report_path, failure)
    print(json.dumps(failure))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
