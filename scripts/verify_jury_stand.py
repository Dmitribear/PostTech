"""Rehearse only marked fictional jury accounts; preserve mutation keys on rerun."""
import argparse
from datetime import date, timedelta
import json
from uuid import uuid4
from verify_live_workflow import API, ROOT, require, read_json, save_checkpoint, checkpoint_lock, now


def run(base, read_only=False):
    accounts = read_json(ROOT / '.local/jury-credentials.json')
    api = API(base)
    profiles = {}
    api.call('GET', '/health/ready')
    api.call('GET', '/profile', expected=401)
    for actor, role in [('employee', 'worker'), ('manager', 'manager'), ('hr', 'hr_admin')]:
        account = accounts[actor]
        require(account['email'] == f"jury.{actor}+{accounts['fixture_id']}@posttech.demo", 'Unexpected jury account')
        login = api.call('POST', '/auth/login', body={k: account[k] for k in ('email', 'password')})
        api.tokens[actor] = login['access_token']
        profile = api.call('GET', '/profile', actor)
        require(profile['role'] == role and profile['external_source'] == 'posttech-jury-fixture'
                and profile['id'] == account['profile_id'], 'Unexpected jury profile')
        profiles[actor] = profile
        api.call('GET', '/academy/courses', actor)
        api.call('GET', '/requests?scope=mine', actor)
    require(profiles['employee']['manager_id'] == profiles['manager']['id'], 'Manager mismatch')
    api.call('GET', '/requests?scope=review', 'employee', expected=403)
    if read_only:
        return {'status': 'passed', 'roles': 3, 'mode': 'read_only', 'checked_at': now()}
    path = ROOT / '.local/jury-rehearsal.json'
    with checkpoint_lock(path):
        state = read_json(path) if path.exists() else {'fixture_id': accounts['fixture_id'], 'key': str(uuid4()),
            'date': (date.today() + timedelta(days=40)).isoformat()}
        require(state['fixture_id'] == accounts['fixture_id'], 'Checkpoint fixture mismatch')
        save_checkpoint(path, state)
        body = {'request_type': 'leave', 'start_date': state['date'], 'end_date': state['date'],
                'comment': 'Демонстрация жюри: семейный день'}
        created = api.call('POST', '/requests', 'employee', body, expected=201, key=state['key'])
        require(api.call('POST', '/requests', 'employee', body, expected=201, key=state['key'])['id'] == created['id'], 'Duplicate request')
        state['request_id'] = created['id']
        save_checkpoint(path, state)
        decision = {'status': 'approved', 'reviewer_comment': 'Демонстрация жюри: отпуск согласован'}
        api.call('PATCH', f"/requests/{created['id']}/review", 'employee', decision, expected=403)
        reviewed = api.call('PATCH', f"/requests/{created['id']}/review", 'manager', decision)
        require(reviewed['status'] == 'approved' and reviewed['reviewed_by'] == profiles['manager']['id'], 'Approval failed')
        notifications = api.rows('/notifications', 'employee')
        require(any(n.get('request_id') == created['id'] for n in notifications), 'Notification missing')
        course = '41000000-0000-4000-8000-000000000001'
        assigned = api.call('GET', '/academy/my-courses', 'employee')
        if not any(c['course_id'] == course for c in assigned):
            api.call('POST', '/academy/assignments', 'manager', {'employee_id': profiles['employee']['id'], 'course_id': course}, expected=201)
        api.call('GET', f'/academy/courses/{course}', 'employee')
        api.call('GET', '/academy/team', 'manager')
        api.call('GET', '/team', 'hr')
        state.update(status='passed', roles=3, course_id=course, checked_at=now(),
                     checks=['three_role_login', 'employee_review_forbidden', 'leave_created', 'retry_no_duplicate',
                             'manager_approved', 'employee_notified', 'course_assigned', 'manager_progress_visible', 'hr_team_visible'])
        save_checkpoint(path, state)
        return {k: state[k] for k in ('status', 'roles', 'checked_at', 'checks')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:8010')
    p.add_argument('--read-only', action='store_true')
    args = p.parse_args()
    try:
        print(json.dumps(run(args.base_url, args.read_only)))
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__,
                          'message': str(exc) if type(exc).__name__ == 'VerificationError' else 'Check local configuration and reuse checkpoint'}))
        raise SystemExit(1)
