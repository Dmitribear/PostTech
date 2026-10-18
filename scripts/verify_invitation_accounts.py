"""Prepare disposable invitation accounts; Resend's test inbox simulates delivery."""

from datetime import date
import hashlib
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client
from provision_live_accounts import save_private
from verify_live_workflow import API, VerificationError, read_json, require

STATE = ROOT / '.local/activation-credentials.json'


def run(mode):
    require(str(get_settings().supabase_url).rstrip('/') == 'https://zcsoipcwymhowmvnytxf.supabase.co', 'Unexpected project')
    db = get_supabase_client()
    if mode == 'cleanup':
        data = read_json(STATE)
        for account in data['accounts']:
            require(account['email'] == f"delivered+posttech-{data['run_id']}-{account['role']}@resend.dev", 'Not a test inbox')
            invite = db.table('registration_invitations').select('id,email,employee_code').eq('id', account['invitation_id']).execute().data
            require(not invite or (invite[0]['email'] == account['email'] and invite[0]['employee_code'] == account['employee_code']), 'Invitation scope mismatch')
            db.table('registration_invitations').delete().eq('id', account['invitation_id']).eq('email', account['email']).execute()
            rows = db.table('employee_profiles').select('id,email,employee_code,external_source').eq('email', account['email']).execute().data
            for row in rows:
                require(row['employee_code'] == account['employee_code'] and row['external_source'] == 'hr-invitation', 'Profile scope mismatch')
                db.table('employee_profiles').delete().eq('id', row['id']).eq('employee_code', account['employee_code']).execute()
            if account.get('auth_id'):
                user = db.auth.admin.get_user_by_id(account['auth_id']).user
                require(user.email == account['email'], 'Auth scope mismatch')
                db.auth.admin.delete_user(account['auth_id'])
        STATE.unlink()
        print('Disposable invitation profiles, invitations and Auth users removed.')
        return

    require(not STATE.exists(), 'Clean up the previous fixture before preparing another')
    accounts = read_json(ROOT / '.local/scenario-credentials.json')
    require(accounts['project_ref'] == 'zcsoipcwymhowmvnytxf', 'Unexpected fixture project')
    api = API('http://127.0.0.1:8000')
    for actor in ('hr', 'employee'):
        account = accounts[actor]
        require(account['email'] == f"scenario.{actor}+{accounts['fixture_id']}@posttech.demo", 'Fixture identity mismatch')
        auth = api.call('POST', '/auth/login', body={k: account[k] for k in ('email', 'password')})
        api.tokens[actor] = auth['access_token']
    state = {'run_id': uuid4().hex[:12], 'accounts': []}
    save_private(STATE, state)
    for role in ('worker', 'manager', 'director', 'hr_admin'):
        email = f"delivered+posttech-{state['run_id']}-{role}@resend.dev"
        employee_code = f"ACTCHECK-{state['run_id']}-{role}"
        details = {'email': email, 'employee_code': employee_code, 'company': 'PostTech synthetic check', 'job_title': 'Проверка приглашения', 'department': 'Проверка регистрации', 'hired_at': date.today().isoformat(), 'role': role, 'vacation_days_remaining': 24}
        api.call('POST', '/auth/invitations', 'employee', details, expected=403)
        invitation = api.call('POST', '/auth/invitations', 'hr', details, expected=201)
        account = {'role': role, 'email': email, 'employee_code': employee_code, 'password': 'Test9-' + secrets.token_urlsafe(24), 'code': invitation['invitation_code'], 'invitation_id': invitation['id'], 'mail_status': invitation['email_status']}
        state['accounts'].append(account)
        save_private(STATE, state)
        require(invitation['email_status'] == 'accepted', 'Invitation email was not accepted by Resend')
        checked = api.call('POST', '/auth/invitations/check', body={'invitation_code': account['code']})
        require(checked['role'] == role and checked['email'] == email, 'HR assignment not preserved')
        api.call('POST', '/auth/register', body={'invitation_code': account['code'], 'first_name': 'Тест', 'last_name': role, 'password': account['password'], 'role': 'hr_admin'}, expected=422)
        digest = hashlib.sha256(account['code'].encode()).hexdigest()
        db.rpc('prepare_registration_invitation', {'p_token_hash': digest, 'p_first_name': 'Тест', 'p_last_name': role, 'p_resend': False}).execute()
        # The SMTP channel is checked separately; obtain a real Auth OTP without an inbox.
        link = db.auth.admin.generate_link({'type': 'signup', 'email': email, 'password': account['password'], 'options': {'data': {'role': 'hr_admin'}}})
        account['auth_id'] = str(link.user.id)
        account['otp'] = link.properties.email_otp
        save_private(STATE, state)
        api.call('POST', '/auth/verify-registration', body={'invitation_code': account['code'], 'token': '00000000'}, expected=400)
        print(json.dumps({'role': role, 'mail': account['mail_status'], 'unauthorized_issue': 'denied', 'forged_role': 'denied', 'invalid_otp': 'denied'}), flush=True)


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ('prepare', 'cleanup'), 'Use prepare or cleanup')
        run(sys.argv[1])
    except Exception as exc:
        print('Invitation fixture check failed: ' + (str(exc) if isinstance(exc, VerificationError) else type(exc).__name__))
        raise SystemExit(1)
