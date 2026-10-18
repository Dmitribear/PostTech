"""Exercise the Supabase launcher with fake Docker; no containers or messages."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


@pytest.mark.skipif(not POWERSHELL, reason="Windows launcher test")
@pytest.mark.parametrize("scenario", [
    "plain", "telegram", "preserve", "shortcut", "saved", "local_model",
    "missing_token", "first_setup", "token_failed", "compose_failed",
    "bad_lan", "bad_page", "bad_database", "foreign_project", "unknown_overlay", "bad_port", "disable_telegram",
])
def test_portal_launcher_preserves_config_and_private_settings(tmp_path, scenario):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("start_portal.ps1", "start_docker.ps1"):
        shutil.copy2(ROOT / "scripts" / name, scripts)
    local = tmp_path / ".local"
    local.mkdir()
    shared = tmp_path / ".env"
    shared.write_text("SUPABASE_KEY=private-cloud-key\nPOSTTECH_HTTP_PORT=8123\nTELEGRAM_BOT_TOKEN=stale-token\n")
    token = "" if scenario == "missing_token" else "123456:" + "x" * 35
    telegram = local / "telegram.env"
    telegram.write_text(
        f"TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_BOT_USERNAME=posttech_test_bot\n"
        "TELEGRAM_WORKER_SECRET=fixture-worker-secret-at-least-32-characters\n"
        "PORTAL_PUBLIC_URL=\n"
    )
    before = shared.read_bytes(), telegram.read_bytes()
    if scenario == "first_setup":
        telegram.unlink()
    if scenario == "saved":
        (local / "portal-docker.json").write_text(json.dumps({
            "telegram": True, "lan_host": "192.168.1.9", "local_model": False,
        }))

    harness = tmp_path / "harness.ps1"
    harness.write_text(r'''
$ErrorActionPreference = 'Stop'
$scenario = $env:PORTAL_TEST_SCENARIO
$env:TELEGRAM_BOT_TOKEN = 'preexisting-process-token'
$env:TELEGRAM_BOT_USERNAME = 'previous_bot'
$env:TELEGRAM_WORKER_SECRET = 'preexisting-process-secret'
$env:POSTTECH_LAN_HOST = '192.168.1.99'
function global:docker {
    Add-Content -LiteralPath (Join-Path $env:PORTAL_TEST_ROOT 'calls.txt') -Value ($args -join ' ')
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info') { 'linux'; return }
    if ($args[0] -eq 'compose' -and $args[1] -eq 'ls') {
        if ($scenario -in @('preserve', 'shortcut', 'local_model', 'foreign_project', 'unknown_overlay')) {
            $folder = if ($scenario -eq 'foreign_project') { Join-Path $env:PORTAL_TEST_ROOT 'other' } else { $env:PORTAL_TEST_ROOT }
            $files = @((Join-Path $folder 'compose.yaml'))
            if ($scenario -in @('preserve', 'shortcut')) { $files += @((Join-Path $folder 'compose.telegram.yaml'), (Join-Path $folder 'compose.lan.yaml')) }
            if ($scenario -eq 'local_model') { $files += Join-Path $folder 'compose.ai.yaml' }
            if ($scenario -eq 'unknown_overlay') { $files += Join-Path $folder 'compose.custom.yaml' }
            ConvertTo-Json -Compress -InputObject @(@{Name='posttech';ConfigFiles=($files -join ',')})
        } else { '[]' }
        return
    }
    if ($args[0] -eq 'ps') { 'fixture-frontend-id'; return }
    if ($args[0] -eq 'inspect') { '{"80/tcp":[{"HostIp":"127.0.0.1","HostPort":"8123"},{"HostIp":"192.168.1.5","HostPort":"8011"}]}'; return }
    if ($args[0] -eq 'compose' -and $args -contains 'port') {
        if ($scenario -eq 'bad_port') { '0.0.0.0:8123' } else { '127.0.0.1:8123'; '192.168.1.5:8011' }
        return
    }
    if ($args -contains 'scripts/prepare_telegram.py') {
        if ($scenario -eq 'first_setup') { Set-Content -LiteralPath (Join-Path $env:PORTAL_TEST_ROOT '.local/telegram.env') -Value 'TELEGRAM_BOT_TOKEN=' }
        if ($scenario -eq 'token_failed') { $global:LASTEXITCODE = 1 }
    }
    if ($args -contains 'up') {
        if ($scenario -eq 'compose_failed') { $global:LASTEXITCODE = 1 }
        @{
            token_from_private = ($env:TELEGRAM_BOT_TOKEN -eq ('123456:' + ('x' * 35)))
            worker_from_private = ($env:TELEGRAM_WORKER_SECRET -eq 'fixture-worker-secret-at-least-32-characters')
            lan_host = $env:POSTTECH_LAN_HOST
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:PORTAL_TEST_ROOT 'resolved.json')
    }
}
function global:Start-Process {
    param($FilePath)
    Add-Content -LiteralPath (Join-Path $env:PORTAL_TEST_ROOT 'opened.txt') -Value $FilePath
}
function global:Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    if ($scenario -eq 'bad_page') { return @{StatusCode=200;Content='wrong page'} }
    return @{StatusCode=200;Content='<script src="/assets/main.js"></script>'}
}
function global:Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    return @{status=$(if ($scenario -eq 'bad_database') { 'unavailable' } else { 'ready' })}
}
try {
    if ($scenario -eq 'shortcut') {
        & (Join-Path $env:PORTAL_TEST_ROOT 'scripts/start_docker.ps1') -NoBrowser
    } else {
        $options = @{OpenBrowser=$true}
        if ($scenario -in @('telegram', 'missing_token', 'first_setup', 'token_failed')) { $options.Telegram = $true }
        if ($scenario -eq 'disable_telegram') { $options.Telegram = $false }
        if ($scenario -eq 'telegram') { $options.LanHost = '192.168.1.7' }
        if ($scenario -eq 'bad_lan') { $options.LanHost = '0.0.0.0' }
        & (Join-Path $env:PORTAL_TEST_ROOT 'scripts/start_portal.ps1') @options
    }
} catch {
    Write-Output $_.Exception.Message
    exit 1
} finally {
    @{
        token_restored = ($env:TELEGRAM_BOT_TOKEN -eq 'preexisting-process-token')
        worker_restored = ($env:TELEGRAM_WORKER_SECRET -eq 'preexisting-process-secret')
        lan_restored = ($env:POSTTECH_LAN_HOST -eq '192.168.1.99')
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:PORTAL_TEST_ROOT 'restored.json')
}
''', encoding="utf-8")
    env = os.environ | {"PORTAL_TEST_ROOT": str(tmp_path), "PORTAL_TEST_SCENARIO": scenario}
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        env=env, capture_output=True, timeout=20,
    )
    output = (result.stdout + result.stderr).decode(errors="replace")
    for private_value in ("private-cloud-key", "preexisting-process-token", "fixture-worker-secret-at-least-32-characters", "123456:" + "x" * 35):
        assert private_value not in output
    calls = (tmp_path / "calls.txt").read_text()
    successful = scenario in {"plain", "telegram", "preserve", "shortcut", "saved", "local_model"}
    assert (result.returncode == 0) == successful, output
    assert shared.read_bytes() == before[0]
    if scenario != "first_setup":
        assert telegram.read_bytes() == before[1]
    restored = json.loads((tmp_path / "restored.json").read_text(encoding="utf-8-sig"))
    assert all(restored.values())
    assert "--remove-orphans" not in calls
    assert "compose.demo.yaml" not in calls
    assert "prepare_docker.py" not in calls
    if scenario in {"missing_token", "first_setup", "token_failed", "bad_lan", "foreign_project", "unknown_overlay", "disable_telegram"}:
        assert " up " not in calls
    if successful:
        assert "up --detach --build --wait" in calls
        assert "--project-name posttech" in calls
        state = json.loads((local / "portal-docker.json").read_text(encoding="utf-8-sig"))
        enabled = scenario in {"telegram", "preserve", "shortcut", "saved"}
        assert state["telegram"] == enabled
        assert ("compose.telegram.yaml" in calls) == enabled
        assert ("compose.ai.yaml" in calls) == (scenario == "local_model")
        assert ("scripts/prepare_telegram.py --check" in calls) == enabled
        if enabled:
            resolved = json.loads((tmp_path / "resolved.json").read_text(encoding="utf-8-sig"))
            assert resolved["token_from_private"] and resolved["worker_from_private"]
            expected_host = {"telegram": "192.168.1.7", "preserve": "192.168.1.5", "shortcut": "192.168.1.5", "saved": "192.168.1.9"}[scenario]
            assert state["lan_host"] == resolved["lan_host"] == expected_host
    opened = tmp_path / "opened.txt"
    assert opened.exists() == (successful and scenario != "shortcut")
