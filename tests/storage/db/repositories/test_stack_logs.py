"""Tests for StackLogsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from application.storage.db.repositories.stack_logs import StackLogsRepository


def _repo(conn) -> StackLogsRepository:
    return StackLogsRepository(conn)


class TestInsert:
    def test_inserts_log(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-1",
            endpoint="/api/answer",
            level="info",
            user_id="u1",
            api_key="k1",
            query="what is python?",
            stacks=[{"component": "retriever", "data": {"docs": 3}}],
        )
        row = pg_conn.execute(
            text("SELECT * FROM stack_logs WHERE activity_id = 'act-1'")
        ).fetchone()
        assert row is not None
        mapping = dict(row._mapping)
        assert mapping["endpoint"] == "/api/answer"
        assert mapping["level"] == "info"
        assert mapping["user_id"] == "u1"
        assert mapping["stacks"] == [{"component": "retriever", "data": {"docs": 3}}]

    def test_inserts_with_empty_stacks(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(activity_id="act-2", level="error")
        row = pg_conn.execute(
            text("SELECT stacks FROM stack_logs WHERE activity_id = 'act-2'")
        ).fetchone()
        assert row is not None
        assert dict(row._mapping)["stacks"] == []

    def test_truncated_query_stored(self, pg_conn):
        repo = _repo(pg_conn)
        long_query = "x" * 20000
        repo.insert(activity_id="act-3", query=long_query)
        row = pg_conn.execute(
            text("SELECT query FROM stack_logs WHERE activity_id = 'act-3'")
        ).fetchone()
        assert len(dict(row._mapping)["query"]) == 20000
