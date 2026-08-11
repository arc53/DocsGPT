"""Tests for WikiPagesRepository against a real Postgres instance.

Wiki pages have a FK to ``sources`` (ON DELETE CASCADE), so each test creates a
source row first.
"""

from __future__ import annotations

import pytest

from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.wiki_pages import (
    WikiPageConflict,
    WikiPagesRepository,
    build_wiki_directory_structure,
    rebuild_wiki_directory_structure,
)


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

    def test_records_updated_via(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        page = repo.upsert(sid, "/a.md", "x", updated_via="human")
        assert page["updated_via"] == "human"

    def test_updated_via_overwritten_on_change(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/a.md", "v1", updated_via="agent")
        page = repo.upsert(sid, "/a.md", "v2", updated_via="human")
        assert page["updated_via"] == "human"

    def test_updated_via_unchanged_on_identical_content(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/a.md", "same", updated_via="agent")
        again = repo.upsert(sid, "/a.md", "same", updated_via="human")
        assert again["updated_via"] == "agent"


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

    def test_prefix_underscore_is_literal_not_wildcard(self, pg_conn):
        # ``_`` is a LIKE single-char wildcard; without escaping, listing
        # ``/api_v1/`` would also match the sibling ``/apiXv1/``.
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/api_v1/a.md", "a")
        repo.upsert(sid, "/apiXv1/b.md", "b")
        results = repo.list_by_prefix(sid, "/api_v1/")
        assert {r["path"] for r in results} == {"/api_v1/a.md"}

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

    def test_delete_by_prefix_underscore_is_literal_not_wildcard(self, pg_conn):
        # Deleting ``/api_v1/`` must not also drop the sibling ``/apiXv1/``
        # via the unescaped ``_`` LIKE wildcard.
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        repo.upsert(sid, "/api_v1/a.md", "a")
        repo.upsert(sid, "/apiXv1/b.md", "b")
        assert repo.delete_by_prefix(sid, "/api_v1/") == 1
        assert repo.get_by_path(sid, "/apiXv1/b.md") is not None


class TestExpectedVersion:
    def test_matching_version_updates(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        v1 = repo.upsert(sid, "/a.md", "v1")
        v2 = repo.upsert(sid, "/a.md", "v2", expected_version=v1["version"])
        assert v2["version"] == 2
        assert v2["content"] == "v2"

    def test_stale_version_raises_conflict(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        v1 = repo.upsert(sid, "/a.md", "v1")
        # A concurrent writer bumps the version out from under us.
        repo.upsert(sid, "/a.md", "v2")
        with pytest.raises(WikiPageConflict):
            repo.upsert(sid, "/a.md", "v3", expected_version=v1["version"])
        # The conflicting write left the concurrent value intact.
        assert repo.get_by_path(sid, "/a.md")["content"] == "v2"

    def test_expected_version_ignored_on_new_page(self, pg_conn):
        repo = _repo(pg_conn)
        sid = _make_source(pg_conn)
        page = repo.upsert(sid, "/new.md", "content", expected_version=99)
        assert page["version"] == 1


class TestDirectoryStructure:
    def test_build_tree_shape(self):
        pages = [
            {"path": "/docs/setup.md", "content": "hello", "token_count": 3},
            {"path": "/readme.md", "content": "x", "token_count": 1},
        ]
        tree = build_wiki_directory_structure(pages)
        assert "readme.md" in tree
        assert tree["docs"]["setup.md"]["type"] == "text/markdown"
        assert tree["docs"]["setup.md"]["token_count"] == 3
        assert tree["readme.md"]["size_bytes"] == 1

    def test_rebuild_writes_to_source(self, pg_conn):
        repo = _repo(pg_conn)
        sid = str(
            SourcesRepository(pg_conn).create(
                "rebuild-src", user_id="rebuild-user", type="wiki"
            )["id"]
        )
        repo.upsert(sid, "/a.md", "a")
        repo.upsert(sid, "/dir/b.md", "b")
        tree = rebuild_wiki_directory_structure(pg_conn, sid, "rebuild-user")
        assert "a.md" in tree
        assert "b.md" in tree["dir"]
        stored = SourcesRepository(pg_conn).get(sid, "rebuild-user")
        assert "a.md" in (stored["directory_structure"] or {})

    def test_rebuild_sets_source_tokens_to_sum(self, pg_conn):
        repo = _repo(pg_conn)
        owner = "rebuild-tokens-user"
        sid = str(
            SourcesRepository(pg_conn).create(
                "rebuild-tokens-src", user_id=owner, type="wiki"
            )["id"]
        )
        page_a = repo.upsert(sid, "/a.md", "alpha beta gamma")
        page_b = repo.upsert(sid, "/dir/b.md", "delta epsilon")
        expected = page_a["token_count"] + page_b["token_count"]

        rebuild_wiki_directory_structure(pg_conn, sid, owner)

        stored = SourcesRepository(pg_conn).get(sid, owner)
        assert int(stored["tokens"]) == expected

    def test_rebuild_after_delete_lowers_source_tokens(self, pg_conn):
        repo = _repo(pg_conn)
        owner = "rebuild-delete-user"
        sid = str(
            SourcesRepository(pg_conn).create(
                "rebuild-delete-src", user_id=owner, type="wiki"
            )["id"]
        )
        page_a = repo.upsert(sid, "/a.md", "alpha beta gamma")
        repo.upsert(sid, "/b.md", "delta epsilon")
        rebuild_wiki_directory_structure(pg_conn, sid, owner)

        repo.delete_by_path(sid, "/b.md")
        rebuild_wiki_directory_structure(pg_conn, sid, owner)

        stored = SourcesRepository(pg_conn).get(sid, owner)
        assert int(stored["tokens"]) == page_a["token_count"]


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
