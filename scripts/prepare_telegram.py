"""Prepare private Telegram settings without reading the shared project's .env.

python scripts/prepare_telegram.py
python scripts/prepare_telegram.py --set-token  # hidden terminal input
python scripts/prepare_telegram.py --check      # getMe only; sends no messages
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}")
USERNAME_RE = re.compile(r"[A-Za-z0-9_]{5,32}")


def prepare(root: Path = ROOT) -> Path:
    target = root / ".local" / "telegram.env"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    values = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_BOT_USERNAME": "",
        "TELEGRAM_WORKER_SECRET": secrets.token_urlsafe(48),
        "PORTAL_PUBLIC_URL": "",
    }
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Private Telegram settings. Never commit, screenshot or share this file.\n")
        stream.write("# Paste the BotFather token below, then run prepare_telegram.py --check.\n")
        stream.write("# Optional PORTAL_PUBLIC_URL must be public HTTPS for the portal inside Telegram.\n")
        stream.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    return target


def read_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_value(path: Path, key: str, value: str) -> None:
    if any(character in value for character in "\r\n"):
        raise ValueError("A setting must fit on one line")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    replacement = f"{key}={value}"
    found = False
    output = []
    for line in lines:
        if line.partition("=")[0].strip() == key:
            if not found:
                output.append(replacement)
                found = True
        else:
            output.append(line)
    if not found:
        output.append(replacement)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(output) + "\n")
    os.replace(temporary, path)


def check_token(token: str) -> dict:
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("Save the complete BotFather token in TELEGRAM_BOT_TOKEN first")
    # The destination is fixed; never print exception URLs because they contain
    # the bot token. getMe is read-only and cannot send a message to anyone.
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getMe", data=b"", method="POST",
    )
    context = ssl.create_default_context()
    if sys.platform == "win32":
        # Use the OS trust store (also used by Windows browsers) when available.
        # Certificate and hostname verification always remain enabled.
        try:
            import truststore
            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            pass
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Telegram refused the token (HTTP {exc.code}); check BotFather") from None
    except Exception:
        raise ValueError("Could not reach Telegram; check the network and retry") from None
    bot = payload.get("result", {})
    if not payload.get("ok") or not bot.get("is_bot") or not USERNAME_RE.fullmatch(bot.get("username", "")):
        raise ValueError("Telegram returned an invalid bot identity")
    return bot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--set-token", action="store_true")
    args = parser.parse_args()
    path = prepare()
    try:
        if args.set_token:
            value = getpass.getpass("BotFather token (hidden): ").strip()
            if not TOKEN_RE.fullmatch(value):
                raise ValueError("The token format is invalid; settings were not changed")
            write_value(path, "TELEGRAM_BOT_TOKEN", value)
        if args.check or args.set_token:
            values = read_values(path)
            if len(values.get("TELEGRAM_WORKER_SECRET", "")) < 32:
                raise ValueError("TELEGRAM_WORKER_SECRET must contain at least 32 random characters")
            bot = check_token(values.get("TELEGRAM_BOT_TOKEN", ""))
            write_value(path, "TELEGRAM_BOT_USERNAME", bot["username"])
            print(f"Telegram identity verified: @{bot['username']}. No messages were sent.")
        else:
            print("Private settings ready: .local/telegram.env (existing values preserved).")
    except ValueError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
