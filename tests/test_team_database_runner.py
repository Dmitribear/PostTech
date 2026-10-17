"""Safety boundaries for the explicit local-only migration checker."""
import json

import pytest

from scripts.check_team_database import local_connection_options, migration_files


@pytest.mark.parametrize("dsn", [
    "postgresql://user:secret@project.supabase.co:5432/posttech_test_team",
    "host=127.0.0.1 hostaddr=198.51.100.3 port=55432 dbname=posttech_test_team user=test",
    "host=localhost port=55432 dbname=posttech_test_team user=test",
    "host=127.0.0.1 port=55432 dbname=production user=test",
    "host=127.0.0.1 port=55432 dbname=posttech_test_team user=test service=shared",
    "host=127.0.0.1 dbname=posttech_test_team user=test",
    "host=127.0.0.1 port=55432 dbname=posttech_test_team",
    "",
])
def test_remote_indirect_or_non_test_database_is_rejected(dsn):
    with pytest.raises(ValueError):
        local_connection_options(dsn)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_numeric_loopback_overrides_inherited_hostaddr(host, monkeypatch):
    monkeypatch.setenv("PGHOSTADDR", "198.51.100.3")
    options = local_connection_options(f"host={host} port=55432 dbname=posttech_test_team user=test")
    assert options["host"] == options["hostaddr"] == host


@pytest.mark.parametrize("path", ["outside.sql", "database/migrations/../../outside.sql"])
def test_manifest_cannot_execute_sql_outside_migrations(tmp_path, path):
    (tmp_path / "database/migrations").mkdir(parents=True)
    (tmp_path / "outside.sql").write_text("SELECT 1", encoding="utf-8")
    (tmp_path / "database/migration-plan.json").write_text(json.dumps({"migrations": [path]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe migration"):
        migration_files(tmp_path)
