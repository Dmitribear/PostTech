"""Private bootstrap and container boundaries, without live Telegram calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.prepare_docker import prepare as prepare_docker
from scripts.prepare_telegram import prepare, read_values, write_value, check_token

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_preserves_secrets_and_shared_env(tmp_path):
    shared = tmp_path / ".env"
    shared.write_text("SUPABASE_KEY=cloud-secret")
    path = prepare(tmp_path)
    before = path.read_bytes()
    assert len(read_values(path)["TELEGRAM_WORKER_SECRET"]) >= 32
    assert read_values(path)["TELEGRAM_BOT_TOKEN"] == ""
    assert prepare(tmp_path).read_bytes() == before
    write_value(path, "TELEGRAM_BOT_TOKEN", "private-value")
    write_value(path, "TELEGRAM_BOT_USERNAME", "posttech_test_bot")
    assert read_values(path)["TELEGRAM_BOT_TOKEN"] == "private-value"
    assert shared.read_text() == "SUPABASE_KEY=cloud-secret"


def test_no_multiline_setting_injection(tmp_path):
    path = prepare(tmp_path)
    with pytest.raises(ValueError):
        write_value(path, "TELEGRAM_BOT_TOKEN", "token\nSUPABASE_KEY=bad")
    assert read_values(path)["TELEGRAM_BOT_TOKEN"] == ""


def test_bad_token_never_makes_network_request(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("Must not connect"))
    with pytest.raises(ValueError, match="complete BotFather token"):
        check_token("paste-token-here")


def test_network_error_does_not_expose_token(monkeypatch):
    token = "123456:" + "x" * 35
    def fail(*args, **kwargs):
        raise OSError("secret URL " + token)
    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ValueError) as error:
        check_token(token)
    assert token not in str(error.value)


@pytest.mark.parametrize("base", ["compose.yaml", "compose.demo.yaml"])
def test_telegram_overlay_is_optional_and_bot_cannot_read_database(tmp_path, base):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose CLI unavailable")
    local = prepare_docker(tmp_path)
    telegram = prepare(tmp_path)
    write_value(telegram, "TELEGRAM_BOT_TOKEN", "123456:" + "x" * 35)
    write_value(telegram, "TELEGRAM_BOT_USERNAME", "posttech_test_bot")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("POSTTECH_", "TELEGRAM_", "COMPOSE_", "JANA_READER_", "PORTAL_"))}
    result = subprocess.run([
        docker, "compose", "--env-file", str(local), "--env-file", str(telegram),
        "-f", str(ROOT / base), "-f", str(ROOT / "compose.telegram.yaml"),
        "config", "--format", "json",
    ], cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", check=True, timeout=30)
    services = json.loads(result.stdout)["services"]
    bot = services["telegram-bot"]
    assert set(bot["networks"]) == {"private", "telegram"}
    assert not bot.get("ports") and not bot.get("volumes")
    assert not any(key.startswith(("SUPABASE_", "POSTTECH_", "JANA_READER_")) for key in bot["environment"])
    assert "TELEGRAM_BOT_TOKEN" not in services["api"]["environment"]
    assert services["api"]["environment"]["TELEGRAM_WORKER_SECRET"] == bot["environment"]["TELEGRAM_WORKER_SECRET"]
