from datetime import datetime, timezone

import pytest

from app.domain.knowledge.publication import (
    freshness,
    usable,
    snapshot_version,
    public_article,
)
from app.domain.knowledge.jana_errors import JanaUnavailable
from app.infrastructure.ai.jana_reader import LocalReader
from app.infrastructure.config import Settings

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
ARTICLE = {
    "active": True,
    "content": "Approved guidance",
    "reviewed_at": "2026-01-01T00:00:00Z",
    "review_due_at": "2027-01-01T00:00:00Z",
}


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({}, "reviewed"),
        ({"reviewed_at": None}, "unverified"),
        ({"review_due_at": "2026-02-01T00:00:00Z"}, "review_overdue"),
        ({"reviewed_at": "2028-01-01T00:00:00Z"}, "unverified"),
    ],
)
def test_only_current_reviewed_publications_are_usable(changes, expected):
    article = ARTICLE | changes
    assert freshness(article, NOW) == expected
    assert usable(article, NOW) == (expected == "reviewed")
    assert not usable(article | {"active": False}, NOW)


def test_source_edit_changes_snapshot_identity():
    assert snapshot_version(ARTICLE) != snapshot_version(
        ARTICLE | {"content": "Revised"}
    )
    assert (
        public_article(ARTICLE | {"source_url": "https://secret:password@example.com"})[
            "source_url"
        ]
        is None
    )


@pytest.mark.parametrize(
    "url, enabled, allowed",
    [
        ("http://jana-reader:8081", True, True),
        ("http://jana-reader:8081", False, False),
        ("http://other:8081", True, False),
        ("http://jana-reader:8082", True, False),
        ("http://@jana-reader:8081", True, False),
    ],
)
def test_docker_reader_requires_explicit_restricted_opt_in(url, enabled, allowed):
    settings = Settings(jana_reader_url=url, jana_reader_allow_docker_host=enabled)
    if allowed:
        assert LocalReader(settings).url == url
    else:
        with pytest.raises(JanaUnavailable):
            LocalReader(settings)
