import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error

import pytest

from scripts.prepare_docker import prepare as prepare_docker
from scripts.prepare_openai import prepare, check_access, validate_key
from scripts.prepare_telegram import prepare as prepare_telegram, write_value

ROOT = Path(__file__).resolve().parents[1]
KEY = 'sk-' + 'fixture' * 8


def test_preserve_settings_and_shared_env(tmp_path):
    shared = tmp_path / '.env'
    shared.write_text('OPENAI_API_KEY=do-not-read-or-change')
    path = prepare(tmp_path)
    write_value(path, 'OPENAI_API_KEY', KEY)
    before = path.read_bytes()
    assert prepare(tmp_path).read_bytes() == before
    assert shared.read_text() == 'OPENAI_API_KEY=do-not-read-or-change'


@pytest.mark.parametrize('key', ['', 'placeholder', KEY + '\nBAD=1', KEY + '$bad'])
def test_invalid_key(key):
    with pytest.raises(ValueError):
        validate_key(key)


@pytest.mark.parametrize('code', [401, 403, 404, 429, 500])
def test_access_failure_never_exposes_key(monkeypatch, code):
    def fail(request, **kwargs):
        assert request.full_url == 'https://api.openai.com/v1/models/gpt-4o-mini'
        assert request.get_method() == 'GET'
        raise urllib.error.HTTPError(request.full_url, code, KEY, {}, None)
    monkeypatch.setattr('urllib.request.urlopen', fail)
    with pytest.raises(ValueError) as error:
        check_access(KEY, 'gpt-4o-mini')
    assert KEY not in str(error.value)
    assert str(code) in str(error.value)


def test_cloud_compose_excludes_model_and_limits_key_to_api(tmp_path):
    docker = shutil.which('docker')
    if not docker:
        pytest.skip('Docker Compose unavailable')
    local = prepare_docker(tmp_path)
    telegram = prepare_telegram(tmp_path)
    openai = prepare(tmp_path)
    write_value(openai, 'OPENAI_API_KEY', KEY)
    write_value(telegram, 'TELEGRAM_BOT_TOKEN', '123456:' + 'x' * 35)
    write_value(telegram, 'TELEGRAM_BOT_USERNAME', 'posttech_test_bot')
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ('POSTTECH_', 'TELEGRAM_', 'COMPOSE_', 'OPENAI_', 'JANA_', 'PORTAL_'))}
    command = [docker, 'compose']
    for path in [local, telegram, openai]:
        command += ['--env-file', str(path)]
    for path in ['compose.demo.yaml', 'compose.telegram.yaml', 'compose.openai.yaml']:
        command += ['-f', str(ROOT / path)]
    result = subprocess.run(command + ['config', '--format', 'json'], cwd=ROOT,
                            env=env, capture_output=True, text=True, check=True, timeout=30)
    config = json.loads(result.stdout)
    services = config['services']
    assert 'jana-reader' not in services and 'model-init' not in services
    assert 'jana-reader' not in services['api']['depends_on']
    assert services['api']['environment']['JANA_PROVIDER'] == 'openai'
    assert services['api']['environment']['OPENAI_API_KEY'] == KEY
    assert {'private', 'openai'} <= set(services['api']['networks'])
    assert not config['networks']['openai'].get('internal', False)
    assert config['networks']['private']['internal']
    for name, service in services.items():
        if name != 'api':
            assert 'OPENAI_API_KEY' not in service.get('environment', {})
    assert services['db']['volumes'][0]['source'] == 'database'
