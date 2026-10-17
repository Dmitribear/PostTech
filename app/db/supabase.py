from functools import lru_cache

from httpx import Client as HttpxClient, Timeout
from supabase import Client, ClientOptions, create_client

from app.core.config import get_settings


def _secret_value(value: object | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    text = str(value).strip()
    return text or None


def _looks_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.lower()
    return normalized.startswith("replace-with-") or normalized.startswith("your-") or normalized.startswith("example-") or "demo" in normalized or "placeholder" in normalized


def _create_client(url: str, key: str, *, public_auth: bool = False) -> Client:
    # Parallel dashboard calls can fail in the synchronous HTTP/2 reader on
    # Windows. Keep connection pooling and concurrency with HTTP/1.1 instead.
    http_client = HttpxClient(
        http2=False,
        timeout=Timeout(30.0, connect=10.0),
        follow_redirects=True,
    )
    try:
        return create_client(url, key, options=ClientOptions(
            httpx_client=http_client,
            persist_session=not public_auth,
            auto_refresh_token=not public_auth,
            flow_type="implicit" if public_auth else "pkce",
        ))
    except Exception:
        http_client.close()
        raise


@lru_cache

def get_supabase_client() -> Client:
    """Return a process-wide Supabase client using server-side credentials."""
    settings = get_settings()
    url = str(settings.supabase_url).rstrip("/") if settings.supabase_url is not None else None
    key = _secret_value(settings.supabase_key)
    if not url or not key or _looks_placeholder(key):
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required for HR data access and must contain real values")
    if key.lower().startswith("sb_publishable_"):
        raise RuntimeError("SUPABASE_KEY looks wrong: use the Supabase service-role secret key, not the publishable key")
    return _create_client(url, key)


@lru_cache
def get_supabase_auth_client() -> Client:
    """Return a Supabase client using the public key for end-user Auth flows."""
    settings = get_settings()
    url = str(settings.supabase_url).rstrip("/") if settings.supabase_url is not None else None
    anon_key = _secret_value(settings.supabase_anon_key)
    service_key = _secret_value(settings.supabase_key)
    if not url or not anon_key or _looks_placeholder(anon_key):
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required for registration and login and must contain real values")
    if service_key and service_key.lower().startswith("sb_publishable_") and anon_key.lower().startswith("sb_secret_"):
        raise RuntimeError("Supabase keys look swapped: SUPABASE_KEY should be the service-role secret key, and SUPABASE_ANON_KEY should be the public anon key")
    if anon_key.lower().startswith("sb_secret_"):
        raise RuntimeError("SUPABASE_ANON_KEY looks wrong: use the public anon key from the Supabase project, not the secret key")
    return _create_client(url, anon_key, public_auth=True)


def create_supabase_auth_client() -> Client:
    """A fresh Auth state machine per HTTP request, sharing only the HTTP pool.

    persist_session=False still leaves an in-memory SDK session; reusing that
    client can mix simultaneous callers. Reusing its transport is safe while
    each new SDK client owns separate session state and Authorization headers.
    """
    pooled_client = get_supabase_auth_client()
    return create_client(str(pooled_client.supabase_url), pooled_client.supabase_key, options=ClientOptions(
        httpx_client=pooled_client.options.httpx_client,
        persist_session=False,
        auto_refresh_token=False,
        flow_type="implicit",
    ))
