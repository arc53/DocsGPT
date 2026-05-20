"""Tests for MemoriesRepository against a real Postgres instance.

Memories have a FK to user_tools, so each test creates a tool row first.
"""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.memories import MemoriesRepository


def _repo(conn) -> MemoriesRepository:
    return MemoriesRepository(conn)


def _make_tool(conn, user_id: str = "test-user", name: str = "mem-tool") -> str:
    """Insert a user_tools row and return its UUID as a string."""
    return str(
        conn.execute(
            text("INSERT INTO user_tools (user_id, name) VALUES (:uid, :name) RETURNING id"),
            {"uid": user_id, "name": name},
        ).scalar()
    )


class TestUpsert:
    def test_creates_memory(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        doc = repo.upsert("test-user", tool_id, "/docs/readme.md", "Hello world")
        assert doc["path"] == "/docs/readme.md"
        assert doc["content"] == "Hello world"
        assert doc["id"] is not None

    def test_upsert_overwrites_content(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("test-user", tool_id, "/a.txt", "v1")
        doc = repo.upsert("test-user", tool_id, "/a.txt", "v2")
        assert doc["content"] == "v2"

    def test_upsert_is_idempotent_on_same_content(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        first = repo.upsert("test-user", tool_id, "/a.txt", "same")
        second = repo.upsert("test-user", tool_id, "/a.txt", "same")
        assert first["id"] == second["id"]


class TestGetByPath:
    def test_finds_existing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/x", "content")
        fetched = repo.get_by_path("u", tool_id, "/x")
        assert fetched is not None
        assert fetched["content"] == "content"

    def test_returns_none_for_missing(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.get_by_path("u", tool_id, "/nonexistent") is None


class TestListByPrefix:
    def test_lists_matching_prefix(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/docs/a.md", "a")
        repo.upsert("u", tool_id, "/docs/b.md", "b")
        repo.upsert("u", tool_id, "/other/c.md", "c")
        results = repo.list_by_prefix("u", tool_id, "/docs/")
        assert len(results) == 2
        assert {r["path"] for r in results} == {"/docs/a.md", "/docs/b.md"}


class TestDeleteByPath:
    def test_deletes_single(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/x", "c")
        count = repo.delete_by_path("u", tool_id, "/x")
        assert count == 1
        assert repo.get_by_path("u", tool_id, "/x") is None

    def test_delete_nonexistent_returns_zero(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.delete_by_path("u", tool_id, "/nope") == 0


class TestDeleteByPrefix:
    def test_deletes_matching_prefix(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/dir/a", "a")
        repo.upsert("u", tool_id, "/dir/b", "b")
        repo.upsert("u", tool_id, "/other/c", "c")
        count = repo.delete_by_prefix("u", tool_id, "/dir/")
        assert count == 2
        assert repo.get_by_path("u", tool_id, "/other/c") is not None


class TestDeleteAll:
    def test_deletes_all_for_user_tool(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/a", "a")
        repo.upsert("u", tool_id, "/b", "b")
        count = repo.delete_all("u", tool_id)
        assert count == 2
        assert repo.list_by_prefix("u", tool_id, "/") == []


class TestUpdatePath:
    def test_renames_path(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        repo.upsert("u", tool_id, "/old.txt", "content")
        renamed = repo.update_path("u", tool_id, "/old.txt", "/new.txt")
        assert renamed is True
        assert repo.get_by_path("u", tool_id, "/old.txt") is None
        assert repo.get_by_path("u", tool_id, "/new.txt")["content"] == "content"

    def test_rename_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn)
        assert repo.update_path("u", tool_id, "/nope", "/new") is False


class TestDefaultToolMemories:
    """Synthetic-id memory writes work; real-tool delete still cascades via trigger."""

    def test_synthetic_tool_id_memory_write_succeeds(self, pg_conn):
        from application.agents.default_tools import default_tool_id

        repo = _repo(pg_conn)
        synthetic_id = default_tool_id("memory")
        doc = repo.upsert("u-syn-mem", synthetic_id, "/note.txt", "built-in")
        assert doc["content"] == "built-in"
        got = repo.get_by_path("u-syn-mem", synthetic_id, "/note.txt")
        assert got is not None and got["content"] == "built-in"

    def test_built_in_and_explicit_memory_are_separate_stores(self, pg_conn):
        from application.agents.default_tools import default_tool_id

        repo = _repo(pg_conn)
        synthetic_id = default_tool_id("memory")
        explicit_id = _make_tool(pg_conn, user_id="u-two-mem", name="memory")
        repo.upsert("u-two-mem", synthetic_id, "/x.txt", "from built-in")
        repo.upsert("u-two-mem", explicit_id, "/x.txt", "from explicit")
        assert (
            repo.get_by_path("u-two-mem", synthetic_id, "/x.txt")["content"]
            == "from built-in"
        )
        assert (
            repo.get_by_path("u-two-mem", explicit_id, "/x.txt")["content"]
            == "from explicit"
        )

    def test_deleting_real_tool_purges_its_memories(self, pg_conn):
        from sqlalchemy import text

        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn, user_id="u-del-mem", name="memory")
        repo.upsert("u-del-mem", tool_id, "/keep.txt", "data")
        pg_conn.execute(
            text("DELETE FROM user_tools WHERE id = CAST(:id AS uuid)"),
            {"id": tool_id},
        )
        assert repo.get_by_path("u-del-mem", tool_id, "/keep.txt") is None


class TestDeleteOrphans:
    """``delete_orphans`` sweeps the FK-to-trigger orphan window."""

    def test_removes_orphan_with_no_user_tools_row(self, pg_conn):
        import uuid

        repo = _repo(pg_conn)
        orphan_tool_id = str(uuid.uuid4())
        repo.upsert("u-orphan", orphan_tool_id, "/x.txt", "stale")
        deleted = repo.delete_orphans()
        assert deleted == 1
        assert repo.get_by_path("u-orphan", orphan_tool_id, "/x.txt") is None

    def test_keeps_memory_of_a_live_tool(self, pg_conn):
        repo = _repo(pg_conn)
        tool_id = _make_tool(pg_conn, user_id="u-live", name="memory")
        repo.upsert("u-live", tool_id, "/keep.txt", "data")
        assert repo.delete_orphans() == 0
        assert repo.get_by_path("u-live", tool_id, "/keep.txt") is not None

    def test_keeps_synthetic_default_tool_memory(self, pg_conn):
        from application.agents.default_tools import default_tool_id

        repo = _repo(pg_conn)
        synthetic_id = default_tool_id("memory")
        repo.upsert("u-syn", synthetic_id, "/note.txt", "built-in")
        deleted = repo.delete_orphans(keep_tool_ids=[synthetic_id])
        assert deleted == 0
        assert repo.get_by_path("u-syn", synthetic_id, "/note.txt") is not None

    def test_sweeps_orphan_but_spares_synthetic_and_live(self, pg_conn):
        import uuid

        from application.agents.default_tools import default_tool_id

        repo = _repo(pg_conn)
        synthetic_id = default_tool_id("memory")
        live_id = _make_tool(pg_conn, user_id="u-mix", name="memory")
        orphan_id = str(uuid.uuid4())
        repo.upsert("u-mix", synthetic_id, "/syn.txt", "keep-syn")
        repo.upsert("u-mix", live_id, "/live.txt", "keep-live")
        repo.upsert("u-mix", orphan_id, "/orphan.txt", "drop")

        deleted = repo.delete_orphans(keep_tool_ids=[synthetic_id])
        assert deleted == 1
        assert repo.get_by_path("u-mix", synthetic_id, "/syn.txt") is not None
        assert repo.get_by_path("u-mix", live_id, "/live.txt") is not None
        assert repo.get_by_path("u-mix", orphan_id, "/orphan.txt") is None
