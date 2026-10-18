"""Run the Windows launcher with fake Docker/browser commands; never start a bot."""
from contextlib import nullcontext
import importlib.util
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


@pytest.fixture
def bootstrap():
    spec = importlib.util.spec_from_file_location(
        "posttech_local_bootstrap", ROOT / "docker/local/bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_plan_includes_both_branches_and_respects_learning_dependencies():
    plan = json.loads((ROOT / "database/migration-plan.json").read_text(encoding="utf-8"))
    paths = plan["migrations"]
    assert len(paths) == len(set(paths))
    assert set(paths) == {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "database/migrations").glob("*.sql")
    }
    assert "database/migrations/0019_telegram.sql" in paths
    assert paths.index("database/migrations/0009_leave_lessons_outbox.sql") < paths.index(
        "database/migrations/0019_external_learning.sql"
    ) < paths.index("database/migrations/0020_personal_courses.sql")


def test_bootstrap_keeps_independent_0019_ledgers_and_rejects_changed_sql(
    bootstrap, tmp_path, monkeypatch
):
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    migrations = tmp_path / "database/migrations"
    migrations.mkdir(parents=True)
    paths = [
        "database/migrations/0019_telegram.sql",
        "database/migrations/0019_external_learning.sql",
    ]
    for index, path in enumerate(paths):
        (tmp_path / path).write_text(f"SELECT {index};", encoding="utf-8")

    class Ledger:
        def __init__(self):
            self.files = {}
            self.applied_sql = []

        def execute(self, sql, parameters=None):
            if sql.startswith("SELECT checksum"):
                value = self.files.get(parameters[0])
                self.row = (value,) if value else None
            elif sql.startswith("INSERT INTO posttech_bootstrap.files"):
                self.files[parameters[0]] = parameters[1]
            else:
                self.applied_sql.append(sql)
            return self

        def fetchone(self):
            return self.row

        def transaction(self):
            return nullcontext()

    ledger = Ledger()
    for _ in range(2):
        for path in paths:
            bootstrap.apply_file(ledger, path)
    assert set(ledger.files) == set(paths)
    assert ledger.applied_sql == ["SELECT 0;", "SELECT 1;"]
    (tmp_path / paths[0]).write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Already applied SQL changed"):
        bootstrap.apply_file(ledger, paths[0])
    assert len(ledger.applied_sql) == 2


def test_bootstrap_initializes_external_catalog_after_course_migrations(
    bootstrap, monkeypatch
):
    class Connection:
        def execute(self, sql, parameters=None):
            self.row = (
                ("posttech_local", "posttech-local-docker")
                if "purpose FROM posttech_bootstrap.identity" in sql
                else (1,)
            )
            return self

        def fetchone(self):
            return self.row

    monkeypatch.setenv("POSTTECH_LOCAL_BOOTSTRAP", "1")
    monkeypatch.setenv("POSTTECH_DB_PASSWORD", "fixture-password")
    monkeypatch.setattr(bootstrap.psycopg, "connect", lambda **_: nullcontext(Connection()))
    monkeypatch.setattr(bootstrap, "create_accounts", lambda _: None)
    applied = []
    monkeypatch.setattr(bootstrap, "apply_file", lambda _, relative: applied.append(relative))
    bootstrap.main()
    plan = json.loads((ROOT / "database/migration-plan.json").read_text(encoding="utf-8"))
    assert applied[:len(plan["migrations"])] == plan["migrations"]
    assert applied.count("database/seed_external_courses.sql") == 1
    assert applied.index("database/migrations/0020_personal_courses.sql") < applied.index(
        "database/seed_external_courses.sql"
    )
