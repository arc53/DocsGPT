"""Tests for AttachmentsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from application.storage.db.repositories.attachments import AttachmentsRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> AttachmentsRepository:
    return AttachmentsRepository(conn)


class TestCreate:
    def test_creates_attachment(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "file.pdf", "/uploads/file.pdf")
        assert doc["user_id"] == "user-1"
        assert doc["filename"] == "file.pdf"
        assert doc["upload_path"] == "/uploads/file.pdf"
        assert doc["id"] is not None

    def test_creates_with_optional_fields(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "img.png", "/uploads/img.png",
                          mime_type="image/png", size=1024)
        assert doc["mime_type"] == "image/png"
        assert doc["size"] == 1024

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "f", "/p")
        assert doc["_id"] == doc["id"]


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "f", "/p")
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000") is None


class TestListForUser:
    def test_lists_only_own_attachments(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1.pdf", "/a1")
        repo.create("alice", "a2.pdf", "/a2")
        repo.create("bob", "b1.pdf", "/b1")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)

    def test_list_empty_for_unknown_user(self, pg_conn):
        repo = _repo(pg_conn)
        results = repo.list_for_user("nonexistent")
        assert results == []
