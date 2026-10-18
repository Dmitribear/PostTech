"""Generate isolated local Docker secrets without reading or changing .env.

Usage: python scripts/prepare_docker.py
Existing configuration is preserved. No secrets are printed.
"""
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

ROOT = Path(__file__).resolve().parents[1]


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def token(secret, role, now):
    header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = encode(json.dumps({"iss": "supabase", "role": role, "iat": now, "exp": now + 10 * 365 * 86400}, separators=(",", ":")).encode())
    message = f"{header}.{body}"
    return message + "." + encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest())


def prepare(root=ROOT):
    target = root / ".local" / "docker.env"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        print("Existing .local/docker.env preserved")
        return target
    secret, now = secrets.token_hex(32), int(time.time())
    values = {
        "COMPOSE_PROJECT_NAME": "posttech-local",
        "POSTTECH_HTTP_PORT": "8000",
        "POSTTECH_DB_PASSWORD": secrets.token_hex(24),
        "POSTTECH_JWT_SECRET": secret,
        "POSTTECH_ANON_KEY": token(secret, "anon", now),
        "POSTTECH_SERVICE_KEY": token(secret, "service_role", now),
        "POSTTECH_DEMO_PASSWORD": "Local9-" + secrets.token_hex(12),
        "JANA_READER_THREADS": "4",
    }
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Local Docker only. Never commit or share this file.\n")
        stream.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print("Created .local/docker.env; demo password is POSTTECH_DEMO_PASSWORD in that file")
    return target


if __name__ == "__main__":
    prepare()
