"""Tests for UserLogsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.user_logs import UserLogsRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> UserLogsRepository:
    return UserLogsRepository(conn)


class TestInsert:
    def test_inserts_log(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(user_id="u1", endpoint="/api/answer", data={"question": "hi"})
        rows, _ = repo.list_paginated(user_id="u1")
        assert len(rows) == 1
        assert rows[0]["data"]["question"] == "hi"

    def test_allows_null_data(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(user_id="u1")
        rows, _ = repo.list_paginated(user_id="u1")
        assert len(rows) == 1
        assert rows[0]["data"] is None


class TestListPaginated:
    def test_paginates(self, pg_conn):
        repo = _repo(pg_conn)
        for i in range(5):
            repo.insert(user_id="u1", data={"i": i})
        page1, has_more1 = repo.list_paginated(user_id="u1", page=1, page_size=3)
        assert len(page1) == 3
        assert has_more1 is True
        page2, has_more2 = repo.list_paginated(user_id="u1", page=2, page_size=3)
        assert len(page2) == 2
        assert has_more2 is False

    def test_filters_by_user(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(user_id="alice", data={"x": 1})
        repo.insert(user_id="bob", data={"x": 2})
        rows, _ = repo.list_paginated(user_id="alice")
        assert len(rows) == 1
        assert rows[0]["user_id"] == "alice"

    def test_ordered_by_timestamp_desc(self, pg_conn):
        from datetime import datetime, timedelta, timezone

        repo = _repo(pg_conn)
        earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
        later = datetime.now(timezone.utc)
        repo.insert(user_id="u1", data={"order": "first"}, timestamp=earlier)
        repo.insert(user_id="u1", data={"order": "second"}, timestamp=later)
        rows, _ = repo.list_paginated(user_id="u1")
        assert rows[0]["data"]["order"] == "second"
