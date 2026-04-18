"""Tests for PendingToolStateRepository against a real Postgres instance."""

from __future__ import annotations


from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.pending_tool_state import PendingToolStateRepository


def _conv(conn) -> dict:
    return ConversationsRepository(conn).create("user-1", "test conv")


def _repo(conn) -> PendingToolStateRepository:
    return PendingToolStateRepository(conn)


def _sample_state() -> dict:
    return {
        "messages": [{"role": "user", "content": "hello"}],
        "pending_tool_calls": [{"id": "tc-1", "name": "search"}],
        "tools_dict": {"search": {"type": "function"}},
        "tool_schemas": [{"name": "search"}],
        "agent_config": {"model_id": "gpt-4", "llm_name": "openai"},
    }


class TestSaveState:
    def test_creates_state(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        state = _sample_state()
        doc = repo.save_state(conv["id"], "user-1", **state)
        assert doc["user_id"] == "user-1"
        assert doc["messages"] == state["messages"]
        assert doc["pending_tool_calls"] == state["pending_tool_calls"]
        assert doc["expires_at"] is not None

    def test_upsert_replaces_existing(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        state = _sample_state()
        repo.save_state(conv["id"], "user-1", **state)
        state["messages"] = [{"role": "user", "content": "updated"}]
        doc2 = repo.save_state(conv["id"], "user-1", **state)
        # Same row, updated content
        assert doc2["messages"] == [{"role": "user", "content": "updated"}]

    def test_save_with_client_tools(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        state = _sample_state()
        state["client_tools"] = [{"name": "browser"}]
        doc = repo.save_state(conv["id"], "user-1", **state)
        assert doc["client_tools"] == [{"name": "browser"}]


class TestLoadState:
    def test_loads_existing(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        loaded = repo.load_state(conv["id"], "user-1")
        assert loaded is not None
        assert loaded["agent_config"]["model_id"] == "gpt-4"

    def test_load_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.load_state("00000000-0000-0000-0000-000000000000", "u") is None


class TestDeleteState:
    def test_deletes(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.save_state(conv["id"], "user-1", **_sample_state())
        assert repo.delete_state(conv["id"], "user-1") is True
        assert repo.load_state(conv["id"], "user-1") is None

    def test_delete_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.delete_state("00000000-0000-0000-0000-000000000000", "u") is False


class TestCleanupExpired:
    def test_cleanup_removes_expired(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        # Create a state with TTL of 0 seconds (already expired)
        repo.save_state(conv["id"], "user-1", **_sample_state(), ttl_seconds=0)
        deleted = repo.cleanup_expired()
        assert deleted >= 1
        assert repo.load_state(conv["id"], "user-1") is None
