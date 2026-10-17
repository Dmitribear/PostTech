"""Knowledge edits invalidate a prior review on real PostgreSQL."""
from contextlib import contextmanager
from uuid import uuid4
import pytest
from test_request_workflow_db import DATABASE_URL, MIGRATIONS, db as legacy_db

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='Set POSTTECH_TEST_DATABASE_URL for real PostgreSQL tests')


def test_review_is_cleared_on_content_edit_but_not_review_metadata():
    with contextmanager(legacy_db.__wrapped__)() as database:
        with database.connect(None) as connection:
            article = str(uuid4())
            connection.execute("INSERT INTO public.knowledge_articles(id,title,content,source_title,created_at) VALUES(%s,'Leave','Original','Test','2025-01-01')", (article,))
            migration = (MIGRATIONS / '0006_knowledge_freshness.sql').read_text(encoding='utf-8')
            connection.execute(migration)
            connection.execute(migration)  # Safe redeployment must preserve metadata.
            assert connection.execute('SELECT updated_at=created_at,reviewed_at IS NULL FROM public.knowledge_articles WHERE id=%s', (article,)).fetchone() == (True, True)
            connection.execute("UPDATE public.knowledge_articles SET reviewed_at=now(),review_due_at=now()+interval '30 days' WHERE id=%s", (article,))
            assert connection.execute('SELECT reviewed_at IS NOT NULL FROM public.knowledge_articles WHERE id=%s', (article,)).fetchone() == (True,)
            connection.execute("UPDATE public.knowledge_articles SET content='Changed',reviewed_at=now() WHERE id=%s", (article,))
            assert connection.execute('SELECT reviewed_at IS NULL,review_due_at IS NULL,updated_at>created_at FROM public.knowledge_articles WHERE id=%s', (article,)).fetchone() == (True, True, True)
