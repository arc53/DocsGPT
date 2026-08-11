"""Tests for UserLogsRepository against a real Postgres instance.

The repository is now write-only: the read path is the unified timeline
in ``api/user/analytics/routes.py`` (GetUserLogs), covered by the route
tests. Inserts are verified with raw SQL here.
"""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.user_logs import UserLogsRepository


def _rows(conn, user_id):
    result = conn.execute(
        text(
            "SELECT * FROM user_logs WHERE user_id = :u ORDER BY timestamp DESC"
        ),
        {"u": user_id},
    )
    return [dict(r._mapping) for r in result.fetchall()]


class TestInsert:
    def test_inserts_log(self, pg_conn):
        repo = UserLogsRepository(pg_conn)
        repo.insert(user_id="u1", endpoint="/api/answer", data={"question": "hi"})
        rows = _rows(pg_conn, "u1")
        assert len(rows) == 1
        assert rows[0]["data"]["question"] == "hi"
        assert rows[0]["endpoint"] == "/api/answer"

    def test_allows_null_data(self, pg_conn):
        repo = UserLogsRepository(pg_conn)
        repo.insert(user_id="u1")
        rows = _rows(pg_conn, "u1")
        assert len(rows) == 1
        assert rows[0]["data"] is None

    def test_explicit_timestamp_is_stored(self, pg_conn):
        from datetime import datetime, timedelta, timezone

        repo = UserLogsRepository(pg_conn)
        earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
        repo.insert(user_id="u1", data={"order": "first"}, timestamp=earlier)
        repo.insert(user_id="u1", data={"order": "second"})
        rows = _rows(pg_conn, "u1")
        assert rows[0]["data"]["order"] == "second"
        assert rows[1]["data"]["order"] == "first"
