"""Publication, freshness and snapshot identity shared by API and local demo."""
import hashlib
import json
from urllib.parse import urlsplit
from datetime import datetime, timezone

FIELDS = "id,title,content,source_title,source_url,active,version,updated_at,reviewed_at,review_due_at,editorial_state"


def _timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (TypeError, ValueError):
        return None


def freshness(article: dict, now=None) -> str:
    now = now or datetime.now(timezone.utc)
    reviewed = _timestamp(article.get("reviewed_at"))
    due = _timestamp(article.get("review_due_at"))
    if reviewed is None or reviewed > now or due is None or due <= reviewed:
        return "unverified"
    return "review_overdue" if due <= now else "reviewed"


def usable(article: dict, now=None) -> bool:
    return (article.get("active", True) is True
            and article.get("editorial_state", "legacy") in {"published", "legacy"}
            and freshness(article, now) == "reviewed")


def snapshot_version(article: dict) -> str:
    fields = {k: article.get(k) for k in FIELDS.split(",")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False,
                                    default=str).encode("utf-8")).hexdigest()[:24]


def metadata(article: dict) -> dict:
    return {"version": snapshot_version(article), "freshness": freshness(article),
            **{key: article.get(key) for key in ("updated_at", "reviewed_at", "review_due_at")}}


def public_article(article: dict) -> dict:
    result = {key: article.get(key) for key in ("id", "title", "content", "source_title", "source_url")} | metadata(article)
    try:
        url = urlsplit(result.get("source_url") or "")
        if url.scheme not in {"https", "http"} or not url.netloc or url.username or url.password:
            result["source_url"] = None
    except ValueError:
        result["source_url"] = None
    return result
