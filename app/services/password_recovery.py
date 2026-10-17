"""Bounded, thread-safe abuse protection for anonymous recovery endpoints.

This supplements Supabase Auth's project-wide rate limits, rather than replacing
them. The local counters are per worker and reset on restart. Deployments with
multiple workers should also apply a shared reverse-proxy/IP rate limit.
No email address, IP address, password, token, or recovery session is retained.
"""

from collections import OrderedDict
from hashlib import sha256
from hmac import digest
from math import ceil
from secrets import token_bytes
from threading import Lock
from time import monotonic

from fastapi import HTTPException


COOLDOWN_SECONDS = 60


class RecoveryLimiter:
    def __init__(self, max_entries: int = 10000):
        self._secret = token_bytes(32)
        self._entries: OrderedDict[bytes, tuple[float, int]] = OrderedDict()
        self._lock = Lock()
        self._max_entries = max_entries

    def _take(self, scope: str, identity: str, limit: int, seconds: int) -> int:
        key = digest(self._secret, f"{scope}:{identity}".encode(), sha256)
        now = monotonic()
        with self._lock:
            # Windows vary in length; insertion order is not expiry order.
            expired = [entry for entry, (until, _) in self._entries.items() if until <= now]
            for entry in expired:
                del self._entries[entry]
            if key not in self._entries and len(self._entries) >= self._max_entries:
                # Fail closed instead of letting identity churn evict active limits.
                return COOLDOWN_SECONDS
            until, count = self._entries.get(key, (now + seconds, 0))
            if count >= limit:
                return max(1, ceil(until - now))
            self._entries[key] = (until, count + 1)
        return 0

    def allow_send(self, email: str, peer: str) -> bool:
        wait = self._take("send-ip", peer, 10, 600)
        if wait:
            raise HTTPException(status_code=429,
                detail="Please wait before requesting another reset code",
                headers={"Retry-After": str(wait)})
        # A repeated address gets the same neutral success as the first request.
        # The cooldown is independent of whether an account actually exists.
        return self._take("send-email", email.casefold(), 1, COOLDOWN_SECONDS) == 0

    def check_confirmation(self, email: str, peer: str) -> None:
        ip_wait = self._take("confirm-ip", peer, 30, 300)
        email_wait = self._take("confirm-email", email.casefold(), 5, 300)
        wait = max(ip_wait, email_wait)
        if wait:
            raise HTTPException(status_code=429,
                detail="Too many reset attempts. Try again later",
                headers={"Retry-After": str(wait)})


limiter = RecoveryLimiter()
