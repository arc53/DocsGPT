"""Tests for WikiPagesRepository against a real Postgres instance.

Wiki pages have a FK to ``sources`` (ON DELETE CASCADE), so each test creates a
source row first.
"""

from __future__ import annotations

from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.wiki_pages import WikiPagesRepository


def _repo(conn) -> WikiPagesRepository:
    return WikiPagesRepository(conn)


def _make_source(conn, user_id: str = "wiki-user", name: str = "wiki-src") -> str:
    """Insert a sources row and return its UUID as a string."""
    return str(SourcesRepository(conn).create(name, user_id=user_id, type="wiki")["id"])


class TestUpsert:
    def test_creates_page(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        page = repo.upsert(sid, "/docs/readme.md", "Hello world", title="Readme")
        assert page["path"] == "/docs/readme.md"
        assert page["content"] == "Hello world"
        assert page["title"] == "Readme"
        assert page["version"] == 1
        assert page["embed_status"] == "pending"
        assert page["content_hash"] is not None
        assert page["token_count"] is not None and page["token_count"] > 0

    def test_get_by_path_after_upsert(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/a.md", "content")
        got = repo.get_by_path(sid, "/a.md")
        assert got is not None
        assert got["content"] == "content"

    def test_records_updated_by(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        page = repo.upsert(sid, "/a.md", "x", updated_by="agent-1")
        assert page["updated_by"] == "agent-1"


class TestContentHashShortCircuit:
    def test_identical_content_does_not_bump_version(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        first = repo.upsert(sid, "/a.md", "same")
        second = repo.upsert(sid, "/a.md", "same")
        assert first["id"] == second["id"]
        assert second["version"] == 1
        assert first["content_hash"] == second["content_hash"]

    def test_identical_content_resets_status_unchanged(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/a.md", "same")
        repo.set_embed_status(sid, "/a.md", "embedded")
        # Re-upsert with identical content must not reset embed_status to pending.
        again = repo.upsert(sid, "/a.md", "same")
        assert again["embed_status"] == "embedded"


class TestVersionBump:
    def test_changed_content_bumps_version_and_resets_status(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        v1 = repo.upsert(sid, "/a.md", "v1")
        repo.set_embed_status(sid, "/a.md", "embedded")
        v2 = repo.upsert(sid, "/a.md", "v2")
        assert v2["version"] == 2
        assert v2["content"] == "v2"
        assert v2["embed_status"] == "pending"
        assert v2["content_hash"] != v1["content_hash"]


class TestListByPrefix:
    def test_lists_matching_prefix(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/docs/a.md", "a")
        repo.upsert(sid, "/docs/b.md", "b")
        repo.upsert(sid, "/other/c.md", "c")
        results = repo.list_by_prefix(sid, "/docs/")
        assert {r["path"] for r in results} == {"/docs/a.md", "/docs/b.md"}

    def test_list_for_source_returns_all(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/a.md", "a")
        repo.upsert(sid, "/b.md", "b")
        results = repo.list_for_source(sid)
        assert {r["path"] for r in results} == {"/a.md", "/b.md"}

    def test_list_is_scoped_to_source(self, pg_conn):
        repo = _repo(pg_conn)
        sid1 = _make_source(pg_conn, name="src-1")
        sid2 = _make_source(pg_conn, name="src-2")
        repo.upsert(sid1, "/a.md", "a")
        repo.upsert(sid2, "/a.md", "b")
        assert len(repo.list_for_source(sid1)) == 1
        assert repo.get_by_path(sid1, "/a.md")["content"] == "a"
        assert repo.get_by_path(sid2, "/a.md")["content"] == "b"


class TestUpdatePath:
    def test_renames_page(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/old.md", "content")
        moved = repo.update_path(sid, "/old.md", "/new.md")
        assert moved is True
        assert repo.get_by_path(sid, "/old.md") is None
        assert repo.get_by_path(sid, "/new.md")["content"] == "content"

    def test_rename_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        assert repo.update_path(sid, "/nope.md", "/new.md") is False

    def test_rename_rejects_existing_target(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/a.md", "a")
        repo.upsert(sid, "/b.md", "b")
        assert repo.update_path(sid, "/a.md", "/b.md") is False
        # Both pages survive untouched.
        assert repo.get_by_path(sid, "/a.md")["content"] == "a"
        assert repo.get_by_path(sid, "/b.md")["content"] == "b"


class TestDelete:
    def test_delete_by_path(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/x.md", "c")
        assert repo.delete_by_path(sid, "/x.md") == 1
        assert repo.get_by_path(sid, "/x.md") is None

    def test_delete_by_path_nonexistent_returns_zero(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        assert repo.delete_by_path(sid, "/nope.md") == 0

    def test_delete_by_prefix(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/dir/a.md", "a")
        repo.upsert(sid, "/dir/b.md", "b")
        repo.upsert(sid, "/other/c.md", "c")
        assert repo.delete_by_prefix(sid, "/dir/") == 2
        assert repo.get_by_path(sid, "/other/c.md") is not None


class TestSetEmbedStatus:
    def test_set_embed_status(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/a.md", "a")
        assert repo.set_embed_status(sid, "/a.md", "embedded") is True
        assert repo.get_by_path(sid, "/a.md")["embed_status"] == "embedded"

    def test_set_embed_status_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        assert repo.set_embed_status(sid, "/nope.md", "embedded") is False
