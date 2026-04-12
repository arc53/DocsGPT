"""Tests for FeedbackRepository against a real Postgres instance."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from application.storage.db.repositories.feedback import FeedbackRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> FeedbackRepository:
    return FeedbackRepository(conn)


def _make_conversation_id(pg_conn) -> str:
    """Insert a minimal conversations row and return its id as string.

    feedback has a FK to conversations (added in Tier 3 migration), but
    the FK constraint may not exist yet during early phases. We create a
    row anyway to keep tests realistic.
    """
    cid = str(uuid.uuid4())
    # Only insert if the conversations table exists; otherwise use a random UUID.
    row = pg_conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='conversations'"
        )
    ).scalar()
    if row:
        pg_conn.execute(
            text("INSERT INTO conversations (id, user_id) VALUES (CAST(:id AS uuid), 'test')"),
            {"id": cid},
        )
    return cid


class TestCreate:
    def test_creates_feedback(self, pg_conn):
        repo = _repo(pg_conn)
        cid = _make_conversation_id(pg_conn)
        doc = repo.create(cid, "user-1", 0, "great answer")
        assert doc["conversation_id"] is not None
        assert doc["user_id"] == "user-1"
        assert doc["question_index"] == 0
        assert doc["feedback_text"] == "great answer"

    def test_allows_null_feedback_text(self, pg_conn):
        repo = _repo(pg_conn)
        cid = _make_conversation_id(pg_conn)
        doc = repo.create(cid, "user-1", 1)
        assert doc["feedback_text"] is None


class TestListForConversation:
    def test_lists_feedback_for_conversation(self, pg_conn):
        repo = _repo(pg_conn)
        cid = _make_conversation_id(pg_conn)
        repo.create(cid, "user-1", 0, "good")
        repo.create(cid, "user-1", 1, "bad")
        results = repo.list_for_conversation(cid)
        assert len(results) == 2
        assert results[0]["question_index"] == 0
        assert results[1]["question_index"] == 1

    def test_does_not_mix_conversations(self, pg_conn):
        repo = _repo(pg_conn)
        cid1 = _make_conversation_id(pg_conn)
        cid2 = _make_conversation_id(pg_conn)
        repo.create(cid1, "user-1", 0, "a")
        repo.create(cid2, "user-1", 0, "b")
        assert len(repo.list_for_conversation(cid1)) == 1
