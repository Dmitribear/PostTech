"""Create an isolated synthetic employee/manager pair for the live workflow check.

Run after inspecting/applying the schema and configuring the root .env.
Secrets are saved only in the ignored .local directory and never printed.
Existing accounts, passwords, and employee profiles are not overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supabase import ClientOptions, create_client  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.supabase import _looks_placeholder, _secret_value  # noqa: E402


def save_private(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    temporary.replace(path)


def provision(project_ref: str) -> dict:
    os.chdir(ROOT)
    settings = get_settings()
    url = str(settings.supabase_url or '').rstrip('/')
    if not re.fullmatch(r'[a-z0-9]{20}', project_ref):
        raise RuntimeError('Expected the 20-character Supabase project reference.')
    if urlparse(url).hostname != f'{project_ref}.supabase.co' or urlparse(url).scheme != 'https':
        raise RuntimeError('The .env URL does not match the explicitly selected project.')
    server_key = _secret_value(settings.supabase_key)
    public_key = _secret_value(settings.supabase_anon_key)
    if _looks_placeholder(server_key) or _looks_placeholder(public_key):
        raise RuntimeError('Configure both Supabase keys in the root .env first.')
    if server_key.startswith('sb_publishable_') or public_key.startswith('sb_secret_'):
        raise RuntimeError('Supabase server/public keys appear swapped.')
    options = ClientOptions(auto_refresh_token=False, persist_session=False)
    admin = create_client(url, server_key, options=options)
    # Check the required tables before creating Auth users.
    for table in ('employee_profiles', 'hr_requests', 'request_events', 'notifications'):
        admin.table(table).select('id').limit(1).execute()

    credentials_path = ROOT / '.local' / 'live-credentials.json'
    if credentials_path.exists():
        state = json.loads(credentials_path.read_text(encoding='utf-8'))
        if state.get('project_ref') != project_ref or not state.get('fixture_id'):
            raise RuntimeError('Existing local credentials belong to another or unknown fixture; left unchanged.')
    else:
        fixture_id = uuid4().hex[:12]
        state = {'project_ref': project_ref, 'fixture_id': fixture_id}
        for role in ('employee', 'manager'):
            state[role] = {
                'email': f'e2e.{role}+{fixture_id}@posttech.demo',
                'password': secrets.token_urlsafe(30),
            }
        save_private(credentials_path, state)

    fixture_id = state['fixture_id']
    if not re.fullmatch(r'[a-f0-9]{12}', fixture_id):
        raise RuntimeError('Local fixture identity is invalid; no changes made.')
    summary = {'project_ref': project_ref, 'credentials_file': str(credentials_path), 'accounts': []}
    for role in ('manager', 'employee'):
        account = state[role]
        expected_email = f'e2e.{role}+{fixture_id}@posttech.demo'
        if account.get('email') != expected_email or not isinstance(account.get('password'), str):
            raise RuntimeError('Local fixture credentials do not match their isolated identity.')
        if account.get('auth_user_id'):
            user = admin.auth.admin.get_user_by_id(account['auth_user_id']).user
        else:
            try:
                user = admin.auth.admin.create_user({
                    'email': account['email'], 'password': account['password'],
                    'email_confirm': True,
                    'app_metadata': {'posttech_live_check': fixture_id},
                }).user
            except Exception:
                # Recover a successful create whose response was lost. This cannot
                # reset or take over an existing account: the original password
                # and this fixture's admin-set marker must both match.
                signin = create_client(url, public_key, options=ClientOptions(auto_refresh_token=False, persist_session=False))
                user = signin.auth.sign_in_with_password({
                    'email': account['email'], 'password': account['password'],
                }).user
        if user is None or user.email != expected_email or user.app_metadata.get('posttech_live_check') != fixture_id:
            raise RuntimeError('The Auth account does not match this synthetic fixture; stopped.')
        account['auth_user_id'] = str(user.id)
        save_private(credentials_path, state)

        is_manager = role == 'manager'
        manager_id = None if is_manager else state['manager']['profile_id']
        expected = {
            'auth_user_id': str(user.id),
            'employee_code': f"LIVE-{'MGR' if is_manager else 'EMP'}-{fixture_id}",
            'email': expected_email,
            'role': 'manager' if is_manager else 'worker',
            'external_source': 'posttech-live-check',
            'manager_id': manager_id,
        }
        found = admin.table('employee_profiles').select('*').eq('auth_user_id', str(user.id)).limit(1).execute().data
        if found:
            profile = found[0]
            if any(profile.get(key) != value for key, value in expected.items()):
                raise RuntimeError('An existing profile differs from the synthetic fixture; left unchanged.')
        else:
            rows = admin.table('employee_profiles').insert({
                **expected, 'full_name': 'Тестовый руководитель' if is_manager else 'Тестовый сотрудник',
                'company': 'PostTech · проверка',
                'department': 'Тестовая команда',
                'job_title': 'Руководитель тестовой команды' if is_manager else 'Тестовый оператор',
                'hired_at': '2025-01-01', 'vacation_days_remaining': 18,
            }).execute().data
            if not rows:
                raise RuntimeError('Profile creation returned no row; rerun safely to inspect its state.')
            profile = rows[0]
        account['profile_id'] = str(profile['id'])
        save_private(credentials_path, state)
        summary['accounts'].append({'role': expected['role'], 'email': expected_email, 'profile_id': account['profile_id']})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-ref', required=True, help='Explicit Supabase project reference; must match .env')
    args = parser.parse_args()
    try:
        result = provision(args.project_ref)
    except RuntimeError as error:
        print(json.dumps({'status': 'blocked', 'message': str(error)}, ensure_ascii=False))
        return 1
    except Exception as error:
        # Library exception strings can include response details; do not print secrets.
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__, 'message': 'Provisioning stopped; existing accounts were not reset. Check configuration/schema/access and rerun with the same .local state.'}))
        return 1
    print(json.dumps({'status': 'ready', **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
