"""Read-only checks against the real local Docker portal; no Telegram messages."""
from datetime import UTC, datetime
import json
from pathlib import Path

from dotenv import dotenv_values
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = dotenv_values(ROOT / '.local/docker.env')
    if config.get('COMPOSE_PROJECT_NAME') != 'posttech-local':
        raise SystemExit('Dedicated local Docker configuration required')
    port = int(config['POSTTECH_HTTP_PORT'])
    if not 1 <= port <= 65535:
        raise SystemExit('Invalid local port')
    checks = []
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        print(name + (': passed' if condition else ': FAILED'), flush=True)
        if not condition:
            raise AssertionError(name)
    with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
        check('Local API ready', client.get('/api/v1/health/ready').status_code == 200)
        check('Anonymous cannot read Telegram link', client.get('/api/v1/telegram/status').status_code == 401)
        check('Anonymous cannot claim notification queue', client.get('/api/v1/telegram/outbox').status_code == 401)
        check('Wrong machine key rejected', client.get('/api/v1/telegram/outbox', headers={'X-Telegram-Worker-Key': 'wrong'}).status_code == 401)
        for role, email in [('worker', 'employee@posttech.demo'), ('manager', 'manager@posttech.demo'),
                            ('director', 'director@posttech.demo'), ('hr_admin', 'hr@posttech.demo')]:
            response = client.post('/api/v1/auth/login', json={'email': email, 'password': config['POSTTECH_DEMO_PASSWORD']})
            check(f'{role} real Auth login', response.status_code == 200)
            headers = {'Authorization': 'Bearer ' + response.json()['access_token']}
            profile = client.get('/api/v1/profile', headers=headers)
            check(f'{role} shared HR profile', profile.status_code == 200 and profile.json()['role'] == role)
            result = client.get('/api/v1/telegram/status', headers=headers)
            check(f'{role} Telegram schema and settings ready', result.status_code == 200 and result.json().get('enabled') is True)
            check(f'{role} status exposes no bot or worker secret', 'token' not in result.text.lower() and 'secret' not in result.text.lower())
    report = {'at': datetime.now(UTC).isoformat(), 'transport': 'real local Docker Auth/API/PostgREST/PostgreSQL',
              'shared_supabase_used': False, 'telegram_messages_sent': False, 'checks': checks}
    target = ROOT / '.local/telegram-local-check.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
