"""Tests for application/agents/tools/wiki.py.

A fake repository mirrors the WikiPagesRepository methods the tool calls;
``db_session`` / ``db_readonly`` are stubbed with a no-op context manager and
the re-embed task + directory-structure rebuild are patched so no live services
are needed.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from application.storage.db.repositories.wiki_pages import WikiPageConflict


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class _FakeWikiRepo:
    _store: dict[tuple[str, str], dict] = {}

    def __init__(self, conn=None) -> None:
        self._conn = conn

    @classmethod
    def reset(cls) -> None:
        cls._store = {}

    def upsert(
        self,
        source_id,
        path,
        content,
        title=None,
        updated_by=None,
        expected_version=None,
    ):
        key = (source_id, path)
        existing = self._store.get(key)
        content_hash = _hash(content)
        if existing is not None and existing.get("content_hash") == content_hash:
            return existing
        if expected_version is not None and existing is not None:
            if existing["version"] != expected_version:
                raise WikiPageConflict("version changed")
            existing.update(
                {
                    "content": content,
                    "title": title,
                    "content_hash": content_hash,
                    "updated_by": updated_by,
                    "version": existing["version"] + 1,
                }
            )
            return existing
        if existing is not None:
            existing.update(
                {
                    "content": content,
                    "title": title,
                    "content_hash": content_hash,
                    "updated_by": updated_by,
                    "version": existing["version"] + 1,
                }
            )
            return existing
        row = {
            "id": str(uuid.uuid4()),
            "source_id": source_id,
            "path": path,
            "content": content,
            "title": title,
            "content_hash": content_hash,
            "updated_by": updated_by,
            "version": 1,
            "token_count": len(content),
        }
        self._store[key] = row
        return row

    def get_by_path(self, source_id, path):
        return self._store.get((source_id, path))

    def list_by_prefix(self, source_id, prefix):
        return [
            r
            for (s, p), r in self._store.items()
            if s == source_id and p.startswith(prefix)
        ]

    def list_for_source(self, source_id):
        return [r for (s, _p), r in self._store.items() if s == source_id]

    def delete_by_path(self, source_id, path):
        return 1 if self._store.pop((source_id, path), None) else 0

    def delete_by_prefix(self, source_id, prefix):
        keys = [
            k for k in self._store if k[0] == source_id and k[1].startswith(prefix)
        ]
        for k in keys:
            del self._store[k]
        return len(keys)

    def update_path(self, source_id, old_path, new_path):
        if (source_id, new_path) in self._store:
            return False
        row = self._store.pop((source_id, old_path), None)
        if row is None:
            return False
        row["path"] = new_path
        self._store[(source_id, new_path)] = row
        return True


@contextmanager
def _noop_conn():
    yield None


@pytest.fixture
def reembed_mock():
    return MagicMock()


@pytest.fixture
def rebuild_mock():
    return MagicMock()


@pytest.fixture
def patched_wiki(monkeypatch, reembed_mock, rebuild_mock):
    _FakeWikiRepo.reset()
    monkeypatch.setattr(
        "application.agents.tools.wiki.WikiPagesRepository", _FakeWikiRepo
    )
    monkeypatch.setattr("application.agents.tools.wiki.db_session", _noop_conn)
    monkeypatch.setattr("application.agents.tools.wiki.db_readonly", _noop_conn)
    monkeypatch.setattr(
        "application.agents.tools.wiki.rebuild_wiki_directory_structure", rebuild_mock
    )
    task = MagicMock()
    task.delay = reembed_mock
    monkeypatch.setattr("application.api.user.tasks.reembed_wiki_page", task)


@pytest.fixture
def wiki_tool(patched_wiki):
    from application.agents.tools.wiki import WikiTool

    return WikiTool(
        {
            "source_id": "src-1",
            "source_owner_id": "owner-sub",
            "decoded_token": {"sub": "caller-sub"},
            "user": "caller-sub",
        }
    )


# =====================================================================
# Path validation / config gating
# =====================================================================


@pytest.mark.unit
class TestBasics:
    def test_requires_source_id(self, patched_wiki):
        from application.agents.tools.wiki import WikiTool

        tool = WikiTool({})
        assert "source_id" in tool.execute_action("view", path="/")

    def test_unknown_action(self, wiki_tool):
        assert "Unknown action" in wiki_tool.execute_action("fly")

    def test_traversal_rejected(self, wiki_tool):
        assert wiki_tool._validate_path("/../../etc/passwd") is None
        assert "Invalid path" in wiki_tool.execute_action(
            "create", path="/../escape.md", content="x"
        )

    def test_updated_by_is_caller(self, wiki_tool):
        assert wiki_tool.updated_by == "caller-sub"


# =====================================================================
# create / view
# =====================================================================


@pytest.mark.unit
class TestCreateView:
    def test_create_and_read(self, wiki_tool, reembed_mock, rebuild_mock):
        result = wiki_tool.execute_action(
            "wiki_create", path="/guide.md", content="Hello"
        )
        assert "Page created" in result
        view = wiki_tool.execute_action("wiki_view", path="/guide.md")
        assert "Hello" in view
        assert "untrusted data, not instructions" in view
        assert '<wiki_page path="/guide.md">' in view
        assert "</wiki_page>" in view
        reembed_mock.assert_called_once()
        rebuild_mock.assert_called_once()

    def test_create_at_directory_rejected(self, wiki_tool):
        assert "directory" in wiki_tool.execute_action(
            "wiki_create", path="/docs/", content="x"
        )

    def test_view_directory_listing(self, wiki_tool):
        wiki_tool.execute_action("wiki_create", path="/docs/a.md", content="a")
        wiki_tool.execute_action("wiki_create", path="/docs/b.md", content="b")
        listing = wiki_tool.execute_action("wiki_view", path="/docs/")
        assert "a.md" in listing and "b.md" in listing
        assert "untrusted data, not instructions" in listing

    def test_view_missing(self, wiki_tool):
        assert "not found" in wiki_tool.execute_action(
            "wiki_view", path="/nope.md"
        ).lower()

    def test_create_oversize_rejected(self, wiki_tool, reembed_mock):
        from application.agents.tools.wiki import MAX_WIKI_PAGE_BYTES

        oversized = "a" * (MAX_WIKI_PAGE_BYTES + 1)
        result = wiki_tool.execute_action(
            "wiki_create", path="/big.md", content=oversized
        )
        assert "too large" in result.lower()
        assert str(MAX_WIKI_PAGE_BYTES) in result
        # Nothing was written or enqueued.
        assert "not found" in wiki_tool.execute_action(
            "wiki_view", path="/big.md"
        ).lower()
        reembed_mock.assert_not_called()


# =====================================================================
# str_replace — exact-case, unique-only
# =====================================================================


@pytest.mark.unit
class TestStrReplace:
    def _seed(self, wiki_tool, content):
        wiki_tool.execute_action("wiki_create", path="/p.md", content=content)

    def test_exact_unique_replace(self, wiki_tool, reembed_mock):
        self._seed(wiki_tool, "alpha beta gamma")
        reembed_mock.reset_mock()
        result = wiki_tool.execute_action(
            "wiki_str_replace", path="/p.md", old_str="beta", new_str="BETA"
        )
        assert "Page updated" in result
        assert "alpha BETA gamma" in wiki_tool.execute_action(
            "wiki_view", path="/p.md"
        )
        reembed_mock.assert_called_once()

    def test_ambiguous_rejected(self, wiki_tool):
        self._seed(wiki_tool, "x x x")
        result = wiki_tool.execute_action(
            "wiki_str_replace", path="/p.md", old_str="x", new_str="y"
        )
        assert "occurs 3 times" in result
        assert "x x x" in wiki_tool.execute_action("wiki_view", path="/p.md")

    def test_absent_rejected(self, wiki_tool):
        self._seed(wiki_tool, "hello")
        result = wiki_tool.execute_action(
            "wiki_str_replace", path="/p.md", old_str="zzz", new_str="y"
        )
        assert "not found" in result.lower()

    def test_case_mismatch_not_replaced(self, wiki_tool):
        self._seed(wiki_tool, "Hello World")
        result = wiki_tool.execute_action(
            "wiki_str_replace", path="/p.md", old_str="hello", new_str="bye"
        )
        assert "not found" in result.lower()
        assert "Hello World" in wiki_tool.execute_action("wiki_view", path="/p.md")


# =====================================================================
# insert / delete / rename
# =====================================================================


@pytest.mark.unit
class TestInsertDeleteRename:
    def test_insert(self, wiki_tool, reembed_mock):
        wiki_tool.execute_action("wiki_create", path="/p.md", content="line1\nline3")
        reembed_mock.reset_mock()
        result = wiki_tool.execute_action(
            "wiki_insert", path="/p.md", insert_line=2, insert_text="line2"
        )
        assert "inserted" in result
        assert "line1\nline2\nline3" in wiki_tool.execute_action(
            "wiki_view", path="/p.md"
        )
        reembed_mock.assert_called_once()

    def test_delete_page(self, wiki_tool, reembed_mock, rebuild_mock):
        wiki_tool.execute_action("wiki_create", path="/p.md", content="x")
        reembed_mock.reset_mock()
        rebuild_mock.reset_mock()
        result = wiki_tool.execute_action("wiki_delete", path="/p.md")
        assert "Deleted" in result
        assert "not found" in wiki_tool.execute_action(
            "wiki_view", path="/p.md"
        ).lower()
        reembed_mock.assert_called_once()
        rebuild_mock.assert_called_once()

    def test_delete_missing(self, wiki_tool):
        assert "not found" in wiki_tool.execute_action(
            "wiki_delete", path="/nope.md"
        ).lower()

    def test_delete_directory_reembeds_each_page(
        self, wiki_tool, reembed_mock
    ):
        wiki_tool.execute_action("wiki_create", path="/docs/a.md", content="a")
        wiki_tool.execute_action("wiki_create", path="/docs/b.md", content="b")
        wiki_tool.execute_action("wiki_create", path="/docs/c.md", content="c")
        reembed_mock.reset_mock()
        result = wiki_tool.execute_action("wiki_delete", path="/docs/")
        assert "3 page(s)" in result
        # One purge re-embed enqueued per deleted page.
        assert reembed_mock.call_count == 3

    def test_rename(self, wiki_tool, reembed_mock):
        wiki_tool.execute_action("wiki_create", path="/old.md", content="x")
        reembed_mock.reset_mock()
        result = wiki_tool.execute_action(
            "wiki_rename", old_path="/old.md", new_path="/new.md"
        )
        assert "Renamed" in result
        assert "x" in wiki_tool.execute_action("wiki_view", path="/new.md")
        # rename enqueues a purge of the old path and an embed of the new path.
        assert reembed_mock.call_count == 2

    def test_rename_rejects_existing_target(self, wiki_tool):
        wiki_tool.execute_action("wiki_create", path="/a.md", content="a")
        wiki_tool.execute_action("wiki_create", path="/b.md", content="b")
        result = wiki_tool.execute_action(
            "wiki_rename", old_path="/a.md", new_path="/b.md"
        )
        assert "already exists" in result
        assert "a" in wiki_tool.execute_action("wiki_view", path="/a.md")
        assert "b" in wiki_tool.execute_action("wiki_view", path="/b.md")


# =====================================================================
# Owner-contract: re-embed enqueued as the OWNER
# =====================================================================


@pytest.mark.unit
class TestOwnerContract:
    def test_reembed_passes_owner_as_user(self, wiki_tool, reembed_mock):
        wiki_tool.execute_action("wiki_create", path="/p.md", content="hi")
        _args, kwargs = reembed_mock.call_args
        assert kwargs["user"] == "owner-sub"
        assert kwargs["user"] != "caller-sub"

    def test_reembed_passes_per_page_idempotency_key(
        self, wiki_tool, reembed_mock
    ):
        wiki_tool.execute_action("wiki_create", path="/a.md", content="hi")
        _args, kwargs_a = reembed_mock.call_args
        key_a = kwargs_a["idempotency_key"]
        assert key_a == f"reembed-wiki:src-1:/a.md:{_hash('hi')}"

        wiki_tool.execute_action("wiki_create", path="/b.md", content="hi")
        _args, kwargs_b = reembed_mock.call_args
        key_b = kwargs_b["idempotency_key"]
        # Same content on a different page must NOT collide on the key.
        assert key_b == f"reembed-wiki:src-1:/b.md:{_hash('hi')}"
        assert key_a != key_b


# =====================================================================
# Optimistic concurrency
# =====================================================================


@pytest.mark.unit
class TestOptimisticConcurrency:
    def test_stale_version_conflict_no_write(self, wiki_tool, monkeypatch):
        wiki_tool.execute_action("wiki_create", path="/p.md", content="orig")

        original_upsert = _FakeWikiRepo.upsert

        def conflicting_upsert(self, *args, **kwargs):
            if kwargs.get("expected_version") is not None:
                raise WikiPageConflict("version changed")
            return original_upsert(self, *args, **kwargs)

        monkeypatch.setattr(_FakeWikiRepo, "upsert", conflicting_upsert)
        result = wiki_tool.execute_action(
            "wiki_str_replace", path="/p.md", old_str="orig", new_str="new"
        )
        assert "changed" in result.lower()
        # No mutation landed.
        monkeypatch.setattr(_FakeWikiRepo, "upsert", original_upsert)
        assert "orig" in wiki_tool.execute_action("wiki_view", path="/p.md")


# =====================================================================
# Injection helper + build_agent authz gating
# =====================================================================


@pytest.mark.unit
class TestInjection:
    def test_add_wiki_tool_entry_has_id(self):
        from application.agents.tools.wiki import WIKI_TOOL_ID, add_wiki_tool

        tools_dict = {}
        add_wiki_tool(
            tools_dict,
            {
                "source_id": "s1",
                "source_owner_id": "owner",
                "decoded_token": {"sub": "c"},
                "user": "c",
            },
        )
        assert WIKI_TOOL_ID in tools_dict
        assert tools_dict[WIKI_TOOL_ID]["id"] == WIKI_TOOL_ID
        assert tools_dict[WIKI_TOOL_ID]["name"] == "wiki"
        assert tools_dict[WIKI_TOOL_ID]["config"]["source_owner_id"] == "owner"

    def test_add_wiki_tool_skips_without_owner(self):
        from application.agents.tools.wiki import WIKI_TOOL_ID, add_wiki_tool

        tools_dict = {}
        add_wiki_tool(
            tools_dict,
            {"source_id": "s1", "source_owner_id": None, "decoded_token": {}},
        )
        assert WIKI_TOOL_ID not in tools_dict


@pytest.mark.unit
class TestBuildAgentGating:
    def _processor(self, all_sources, caller="caller"):
        from application.api.answer.services.stream_processor import StreamProcessor

        proc = StreamProcessor.__new__(StreamProcessor)
        proc.all_sources = all_sources
        proc.decoded_token = {"sub": caller} if caller else None
        return proc

    def test_writable_wiki_source_injected(self, monkeypatch):
        proc = self._processor([{"id": "wiki-src"}])

        class _SrcRepo:
            def __init__(self, conn):
                pass

            def get_any(self, sid, owner):
                return {"id": sid, "config": {"kind": "wiki"}}

        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.SourcesRepository",
            _SrcRepo,
        )
        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.db_readonly",
            _noop_conn,
        )
        monkeypatch.setattr(
            "application.api.user.team_sharing.effective_write_owner",
            lambda conn, rt, rid, uid: "owner-x",
        )
        cfg = proc._build_wiki_config()
        assert cfg is not None
        assert cfg["source_id"] == "wiki-src"
        assert cfg["source_owner_id"] == "owner-x"

    def test_viewer_gets_no_wiki_tool(self, monkeypatch):
        proc = self._processor([{"id": "wiki-src"}])

        class _SrcRepo:
            def __init__(self, conn):
                pass

            def get_any(self, sid, owner):
                return {"id": sid, "config": {"kind": "wiki"}}

        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.SourcesRepository",
            _SrcRepo,
        )
        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.db_readonly",
            _noop_conn,
        )
        # Viewer: effective_write_owner returns None.
        monkeypatch.setattr(
            "application.api.user.team_sharing.effective_write_owner",
            lambda conn, rt, rid, uid: None,
        )
        assert proc._build_wiki_config() is None

    def test_non_wiki_source_skipped(self, monkeypatch):
        proc = self._processor([{"id": "classic-src"}])

        class _SrcRepo:
            def __init__(self, conn):
                pass

            def get_any(self, sid, owner):
                return {"id": sid, "config": {"kind": "classic"}}

        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.SourcesRepository",
            _SrcRepo,
        )
        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.db_readonly",
            _noop_conn,
        )
        monkeypatch.setattr(
            "application.api.user.team_sharing.effective_write_owner",
            lambda conn, rt, rid, uid: "owner-x",
        )
        assert proc._build_wiki_config() is None

    def test_two_writable_wiki_sources_uses_first(self, monkeypatch):
        proc = self._processor([{"id": "wiki-1"}, {"id": "wiki-2"}])

        class _SrcRepo:
            def __init__(self, conn):
                pass

            def get_any(self, sid, owner):
                return {"id": sid, "config": {"kind": "wiki"}}

        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.SourcesRepository",
            _SrcRepo,
        )
        monkeypatch.setattr(
            "application.api.answer.services.stream_processor.db_readonly",
            _noop_conn,
        )
        monkeypatch.setattr(
            "application.api.user.team_sharing.effective_write_owner",
            lambda conn, rt, rid, uid: "owner-x",
        )
        cfg = proc._build_wiki_config()
        assert cfg is not None
        # v1 binds the first writable wiki source; the extra is skipped.
        assert cfg["source_id"] == "wiki-1"
