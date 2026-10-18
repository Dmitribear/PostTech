"""Run the Windows launcher with fake Docker/browser commands; never start a bot."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows launcher test")


@pytest.mark.parametrize("scenario", [
    "ready", "first_setup", "token_failed", "compose_failed", "bad_port",
    "bad_page", "windows_engine", "desktop_start", "openai_failed", "local_mode",
])
def test_one_click_launcher_preserves_secrets_and_only_opens_a_ready_site(tmp_path, scenario):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "scripts/start_telegram.ps1", scripts)
    local = tmp_path / ".local"
    local.mkdir()
    docker_env = local / "docker.env"
    telegram_env = local / "telegram.env"
    openai_env = local / "openai.env"
    password = "fixture-private-password"
    token = "fixture-private-token"
    port = "invalid" if scenario == "bad_port" else "8123"
    docker_env.write_text(f"POSTTECH_HTTP_PORT={port}\nPOSTTECH_DEMO_PASSWORD={password}\n")
    telegram_env.write_text(f"TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_WORKER_SECRET=fixture-worker-secret\n")
    openai_env.write_text("OPENAI_API_KEY=fixture-openai-private\n")
    before = (docker_env.read_bytes(), telegram_env.read_bytes(), openai_env.read_bytes())
    if scenario == "first_setup":
        docker_env.unlink()
        telegram_env.unlink()
        openai_env.unlink()
    desktop = tmp_path / "program-files/Docker/Docker/Docker Desktop.exe"
    desktop.parent.mkdir(parents=True)
    desktop.touch()
    harness = tmp_path / "harness.ps1"
    harness.write_text(r'''
$ErrorActionPreference = 'Stop'
$env:ProgramFiles = Join-Path $env:DEMO_TEST_ROOT 'program-files'
$env:LOCALAPPDATA = $env:DEMO_TEST_ROOT
$script:infoCalls = 0
function global:docker {
    Add-Content -LiteralPath (Join-Path $env:DEMO_TEST_ROOT 'calls.txt') -Value ($args -join ' ')
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info') {
        $script:infoCalls++
        if ($env:DEMO_TEST_SCENARIO -eq 'desktop_start' -and $script:infoCalls -eq 1) {
            $global:LASTEXITCODE = 1; return
        }
        if ($env:DEMO_TEST_SCENARIO -eq 'windows_engine') { 'windows' } else { 'linux' }
        return
    }
    if ($args -contains 'scripts/prepare_docker.py') {
        Set-Content -LiteralPath (Join-Path $env:DEMO_TEST_ROOT '.local/docker.env') -Value 'POSTTECH_HTTP_PORT=8123'
    }
    if ($args -contains 'scripts/prepare_telegram.py') {
        $path = Join-Path $env:DEMO_TEST_ROOT '.local/telegram.env'
        if (-not (Test-Path -LiteralPath $path)) { Set-Content -LiteralPath $path -Value 'TELEGRAM_BOT_TOKEN=' }
        if ($args -contains '--set-token') { Set-Content -LiteralPath $path -Value 'TELEGRAM_BOT_TOKEN=fixture-private-token' }
        if ($env:DEMO_TEST_SCENARIO -eq 'token_failed') { $global:LASTEXITCODE = 1 }
    }
    if ($args -contains 'scripts.prepare_openai') {
        $path = Join-Path $env:DEMO_TEST_ROOT '.local/openai.env'
        if (-not (Test-Path -LiteralPath $path)) { Set-Content -LiteralPath $path -Value 'OPENAI_API_KEY=fixture-openai-private' }
        if ($env:DEMO_TEST_SCENARIO -eq 'openai_failed') { $global:LASTEXITCODE = 1 }
    }
    if ($args[0] -eq 'compose' -and $env:DEMO_TEST_SCENARIO -eq 'compose_failed') { $global:LASTEXITCODE = 1 }
}
function global:Start-Process {
    param($FilePath, $WindowStyle)
    Add-Content -LiteralPath (Join-Path $env:DEMO_TEST_ROOT 'opened.txt') -Value $FilePath
}
function global:Start-Sleep { param($Seconds) }
function global:Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    if ($env:DEMO_TEST_SCENARIO -eq 'bad_page') { return @{StatusCode=200;Content='wrong page'} }
    return @{StatusCode=200;Content='<script src="/assets/main.js"></script>'}
}
try {
    & (Join-Path $env:DEMO_TEST_ROOT 'scripts/start_telegram.ps1') -Interactive -OpenBrowser -LocalModel:($env:DEMO_TEST_SCENARIO -eq 'local_mode')
} catch {
    Write-Output $_.Exception.Message
    exit 1
}
''', encoding="utf-8")
    env = os.environ | {
        "DEMO_TEST_ROOT": str(tmp_path), "DEMO_TEST_SCENARIO": scenario,
        "ProgramFiles": str(tmp_path / "program-files"), "LOCALAPPDATA": str(tmp_path),
    }
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        env=env, capture_output=True, timeout=20,
    )
    output = (result.stdout + result.stderr).decode(errors="replace")
    assert password not in output and token not in output
    assert 'fixture-openai-private' not in output
    opened = (tmp_path / "opened.txt").read_text() if (tmp_path / "opened.txt").exists() else ""
    calls = (tmp_path / "calls.txt").read_text()
    successful = scenario in {"ready", "first_setup", "desktop_start", "local_mode"}
    assert (result.returncode == 0) == successful, output
    assert ("http://127.0.0.1:8123" in opened) == successful
    if scenario != "first_setup":
        assert (docker_env.read_bytes(), telegram_env.read_bytes(), openai_env.read_bytes()) == before
        assert "--set-token" not in calls
    else:
        assert "--set-token" in calls and "--rm -it" in calls
    if scenario in {"token_failed", "windows_engine", "openai_failed"}:
        assert " up " not in calls
    if scenario == "desktop_start":
        assert "Docker Desktop.exe" in opened
    if successful:
        assert "compose.demo.yaml" in calls and "compose.telegram.yaml" in calls
        assert "up --detach --build --wait" in calls
        assert ('compose.openai.yaml' in calls) == (scenario != 'local_mode')
        assert ('scripts.prepare_openai' in calls) == (scenario != 'local_mode')
        assert ('stop jana-reader model-init' in calls) == (scenario != 'local_mode')
