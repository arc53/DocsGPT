"""Tests for ConnectorSessionsRepository against a real Postgres instance."""

from __future__ import annotations


from application.storage.db.repositories.connector_sessions import ConnectorSessionsRepository


def _repo(conn) -> ConnectorSessionsRepository:
    return ConnectorSessionsRepository(conn)


class TestUpsert:
    def test_creates_session(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.upsert("user-1", "google", {"token": "abc123"})
        assert doc["user_id"] == "user-1"
        assert doc["provider"] == "google"
        assert doc["session_data"] == {"token": "abc123"}
        assert doc["id"] is not None

    def test_upsert_creates_second_session(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.upsert("user-1", "google", {"token": "v1"})
        assert first["session_data"] == {"token": "v1"}
        # Without a UNIQUE(user_id, provider) constraint, a second upsert
        # creates another row (ON CONFLICT DO NOTHING never fires).
        second = repo.upsert("user-1", "google", {"token": "v2"})
        assert second["session_data"] == {"token": "v2"}


class TestGetByUserProvider:
    def test_finds_existing(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("u", "slack", {"key": "val"})
        fetched = repo.get_by_user_provider("u", "slack")
        assert fetched is not None
        assert fetched["session_data"] == {"key": "val"}

    def test_returns_none_for_missing(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get_by_user_provider("u", "nonexistent") is None

    def test_different_providers_are_separate(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("u", "google", {"g": 1})
        repo.upsert("u", "slack", {"s": 2})
        g = repo.get_by_user_provider("u", "google")
        s = repo.get_by_user_provider("u", "slack")
        assert g["session_data"] == {"g": 1}
        assert s["session_data"] == {"s": 2}


class TestListForUser:
    def test_lists_all_providers(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("alice", "google", {"g": 1})
        repo.upsert("alice", "slack", {"s": 1})
        repo.upsert("bob", "google", {"g": 2})
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)

    def test_list_empty_for_unknown_user(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.list_for_user("nonexistent") == []


class TestDelete:
    def test_deletes_session(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("u", "google", {"t": 1})
        deleted = repo.delete("u", "google")
        assert deleted is True
        assert repo.get_by_user_provider("u", "google") is None

    def test_delete_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        deleted = repo.delete("u", "nonexistent")
        assert deleted is False

    def test_delete_one_provider_leaves_others(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert("u", "google", {"g": 1})
        repo.upsert("u", "slack", {"s": 1})
        repo.delete("u", "google")
        assert repo.get_by_user_provider("u", "google") is None
        assert repo.get_by_user_provider("u", "slack") is not None
