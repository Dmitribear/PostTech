from functools import lru_cache

from supabase import Client, create_client

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
    return create_client(url, key)


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
    return create_client(url, anon_key)
