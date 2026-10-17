"""Local Docker configuration must never inherit shared cloud credentials."""
import base64
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.prepare_docker import prepare, token

ROOT = Path(__file__).resolve().parents[1]


def decode(segment):
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def test_local_config_is_separate_and_preserved(tmp_path):
    shared = tmp_path / ".env"
    shared.write_text("SUPABASE_URL=https://shared.invalid\nSUPABASE_KEY=never-copy-this\n")
    created = prepare(tmp_path)
    assert created == tmp_path / ".local/docker.env"
    content = created.read_text()
    assert "shared.invalid" not in content and "never-copy-this" not in content
    assert "POSTTECH_DEMO_PASSWORD=" in content
    assert prepare(tmp_path).read_text() == content
    assert shared.read_text().endswith("SUPABASE_KEY=never-copy-this\n")


@pytest.mark.parametrize("role", ["anon", "service_role"])
def test_generated_keys_have_valid_independent_role_signatures(role):
    secret = "local-test-secret-with-at-least-32-characters"
    value = token(secret, role, 1000)
    header, payload, signature = value.split(".")
    assert decode(header) == {"alg": "HS256", "typ": "JWT"}
    claims = decode(payload)
    assert claims["role"] == role and claims["iat"] == 1000 and claims["exp"] > claims["iat"]
    actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    assert hmac.compare_digest(actual, hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())


@pytest.fixture
def bootstrap():
    pytest.importorskip("psycopg")
    spec = importlib.util.spec_from_file_location("local_docker_bootstrap", ROOT / "docker/local/bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_requires_explicit_local_mode_before_connecting(bootstrap, monkeypatch):
    monkeypatch.delenv("POSTTECH_LOCAL_BOOTSTRAP", raising=False)
    monkeypatch.setattr(bootstrap.psycopg, "connect", lambda **kwargs: pytest.fail("Must not connect"))
    with pytest.raises(SystemExit, match="only for the local Docker"):
        bootstrap.main()


def test_bootstrap_rejects_manifest_paths_outside_database(bootstrap, tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    for relative in ("../outside.sql", "scripts/unsafe.sql", "database/not-sql.py"):
        with pytest.raises(RuntimeError, match="inside database"):
            bootstrap.apply_file(None, relative)


def test_transaction_wrapper_preserves_plpgsql_blocks(bootstrap):
    source = "begin;\nDO $$\nbegin\n perform 1;\nend $$;\ncommit;\n"
    result = bootstrap.transaction_body(source)
    assert "DO $$\nbegin\n perform 1;\nend $$;" in result
    assert not result.strip().lower().startswith("begin;")
    assert not result.strip().lower().endswith("commit;")


@pytest.mark.parametrize("gpu", [False, True])
def test_compose_exposes_only_frontend_and_keeps_data_and_ai_private(tmp_path, gpu):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI is required; the Docker daemon is not used")
    config = prepare(tmp_path)
    command = [docker, "compose", "--env-file", str(config), "-f", str(ROOT / "compose.yaml")]
    if gpu:
        command += ["-f", str(ROOT / "compose.gpu.yaml")]
    # Never read actual local/shared secrets, including exported shell values.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("POSTTECH_", "COMPOSE_", "JANA_READER_"))}
    result = subprocess.run(command + ["config", "--format", "json"], cwd=ROOT, env=environment,
                            capture_output=True, text=True, encoding="utf-8", check=True, timeout=30)
    parsed = json.loads(result.stdout)
    services = parsed["services"]
    assert parsed["networks"]["private"]["internal"] is True
    assert not parsed["networks"]["edge"].get("internal", False)
    assert set(services["frontend"]["networks"]) == {"edge", "private"}
    assert {name for name, service in services.items() if service.get("ports")} == {"frontend"}
    assert services["frontend"]["ports"][0]["host_ip"] == "127.0.0.1"
    for name in ("api", "db", "auth", "rest", "supabase", "jana-reader", "bootstrap", "workflow-worker"):
        assert set(services[name]["networks"]) == {"private"}
    assert set(services["model-init"]["networks"]) == {"download"}
