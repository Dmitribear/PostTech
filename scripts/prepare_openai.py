"""Keep the demo API key private; validate model access without generating tokens."""
import argparse
import getpass
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

from scripts.prepare_telegram import read_values, write_value

ROOT = Path(__file__).resolve().parents[1]


def prepare(root: Path = ROOT) -> Path:
    path = root / ".local" / "openai.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("# Private. Never commit this file or share screenshots of it.\n"
                         "OPENAI_API_KEY=\nOPENAI_MODEL=gpt-4o-mini\n")
    return path


def validate_key(key: str) -> None:
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{20,}", key):
        raise ValueError("Save a complete OpenAI API key in .local/openai.env (OPENAI_API_KEY).")


def check_access(key: str, model: str) -> None:
    validate_key(key)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise ValueError("Invalid OPENAI_MODEL in .local/openai.env.")
    request = urllib.request.Request(
        "https://api.openai.com/v1/models/" + model,
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise ValueError("OpenAI did not confirm model access.")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"OpenAI access check failed (HTTP {exc.code}). Check key, model and project permissions.") from None
    except (OSError, ValueError):
        raise ValueError("Could not reach OpenAI. Check internet, key and model access.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    path = prepare()
    try:
        values = read_values(path)
        key = values.get("OPENAI_API_KEY", "")
        if not key and args.interactive:
            key = getpass.getpass("OpenAI API key (hidden): ").strip()
            validate_key(key)
            write_value(path, "OPENAI_API_KEY", key)
        check_access(key, values.get("OPENAI_MODEL") or "gpt-4o-mini")
        print("OpenAI model access verified. Balance and generation quota are not checked.")
        return 0
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "Key setup cancelled.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
