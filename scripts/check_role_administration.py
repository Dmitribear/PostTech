"""Run the consolidated role/SQL checks against a disposable test database."""

import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    if not os.environ.get("POSTTECH_TEST_DATABASE_URL"):
        print(
            "Set POSTTECH_TEST_DATABASE_URL to a local posttech_test_* control database."
        )
        return 2
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_admin.py",
            "tests/test_consolidated_schema_db.py",
        ],
        cwd=Path(__file__).resolve().parents[1],
    )


if __name__ == "__main__":
    raise SystemExit(main())
