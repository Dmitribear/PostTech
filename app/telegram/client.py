"""HTTP clients deliberately redact transport errors: Telegram URLs contain secrets."""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import ipaddress
import os
import re
import time
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import SecretStr


class RemoteError(Exception):
    def __init__(self, service: str, status: int = 503, retry_after: int = 5):
        super().__init__(f"{service} request failed ({status})")
        self.service = service
        self.status, self.retry_after = status, min(max(retry_after, 1), 86400)


def public_portal_url(value: str) -> str | None:
    """Telegram Mini Apps require public HTTPS; never offer localhost to a phone."""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if parsed.scheme != 'https' or not host or parsed.username or parsed.password:
            return None
        if host == 'localhost' or '.' not in host or host.endswith(('.localhost', '.local', '.internal')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value.rstrip('/')
    except ValueError:
        return None


@dataclass(frozen=True)
class BotConfig:
    token: SecretStr
    worker_secret: SecretStr
    api_url: str = 'http://api:8000'
    portal_url: str = ''

    @classmethod
    def from_env(cls):
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
        secret = os.environ.get('TELEGRAM_WORKER_SECRET', '').strip()
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token) or len(secret) < 32:
            raise ValueError('Configure TELEGRAM_BOT_TOKEN and TELEGRAM_WORKER_SECRET (32+ characters)')
        base = os.environ.get('TELEGRAM_API_URL', 'http://api:8000').rstrip('/')
        url = urlsplit(base)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Invalid TELEGRAM_API_URL')
        return cls(SecretStr(token), SecretStr(secret), base, os.environ.get('PORTAL_PUBLIC_URL', ''))


def mutation_key(user_id: int, update_id: int, action: str) -> str:
    return str(uuid5(NAMESPACE_URL, f'posttech:telegram:{user_id}:{update_id}:{action}'))


class PortalClient:
    def __init__(self, config: BotConfig, http: httpx.AsyncClient):
        self.config, self.http = config, http

    async def request(self, method, path, user_id=None, *, body=None, key=None, params=None, binary=False):
        if not path.startswith('/') or '://' in path or '..' in path:
            raise ValueError('Internal API path required')
        headers = {'X-Telegram-Worker-Key': self.config.worker_secret.get_secret_value(), 'Accept-Language': 'ru'}
        if user_id is not None:
            headers['X-Telegram-User-Id'] = str(user_id)
        if key:
            headers['Idempotency-Key'] = key
        try:
            response = await self.http.request(method, self.config.api_url + '/api/v1' + path,
                                               headers=headers, json=body, params=params,
                                               timeout=330 if path == '/ai/ask' else 15)
        except httpx.HTTPError:
            raise RemoteError('Portal') from None
        if not response.is_success:
            raise RemoteError('Portal', response.status_code)
        if binary:
            return response.content
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise RemoteError('Portal') from None


class TelegramClient:
    def __init__(self, config: BotConfig, http: httpx.AsyncClient):
        self.config, self.http = config, http
        self._send_locks: dict[int, asyncio.Lock] = {}
        self._last_sent: dict[int, float] = {}

    async def call(self, method: str, data: dict | None = None, *, document: bytes | None = None):
        try:
            kwargs = {'json': data or {}} if document is None else {
                'data': data or {}, 'files': {'document': ('janapost-leaves.ics', document, 'text/calendar')}}
            response = await self.http.post(
                f'https://api.telegram.org/bot{self.config.token.get_secret_value()}/{method}',
                **kwargs, timeout=40)
            result = response.json()
        except (httpx.HTTPError, ValueError):
            raise RemoteError('Telegram') from None
        if not isinstance(result, dict):
            raise RemoteError('Telegram')
        if not response.is_success or result.get('ok') is not True:
            parameters = result.get('parameters')
            parameters = parameters if isinstance(parameters, dict) else {}
            code, retry = result.get('error_code', response.status_code), parameters.get('retry_after', 5)
            raise RemoteError('Telegram', code if isinstance(code, int) else 503,
                              retry if isinstance(retry, int) else 5)
        return result.get('result')

    async def send(self, chat_id: int, text: str, markup: dict | None = None, *, retry_rate_limit=True):
        # Telegram length is measured in UTF-16 code units. 1800 Python characters
        # are safely below 4096 even for astral emoji. No parse_mode: text stays data.
        chunks = [text[i:i + 1800] for i in range(0, len(text), 1800)] or ['—']
        lock = self._send_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            for index, chunk in enumerate(chunks):
                delay = self._last_sent.get(chat_id, 0) + 1.05 - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                data = {'chat_id': chat_id, 'text': chunk, 'link_preview_options': {'is_disabled': True}}
                if markup and index == len(chunks) - 1:
                    data['reply_markup'] = markup
                try:
                    await self.call('sendMessage', data)
                except RemoteError as exc:
                    if exc.status != 429 or not retry_rate_limit:
                        raise
                    await asyncio.sleep(exc.retry_after)
                    await self.call('sendMessage', data)
                self._last_sent[chat_id] = time.monotonic()
