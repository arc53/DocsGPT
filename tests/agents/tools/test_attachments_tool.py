"""Tests for the synthetic attachments tool (docsgpt/agents/tools/attachments.py)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.agents.tools.attachments import (
    ATTACHMENTS_TOOL_ID,
    AttachmentsTool,
    add_attachments_tool,
)
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository

USER = "user-1"


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.storage.db.session.db_readonly", _yield), patch(
        "docsgpt.storage.db.session.db_session", _yield
    ):
        yield


def _make(conn, filename, content, user=USER, **metadata):
    return AttachmentsRepository(conn).create(
        user,
        filename,
        f"/uploads/{filename}",
        mime_type="text/plain",
        content=content,
        token_count=len(content.split()),
        metadata={"extraction": {"status": "ok"}, **metadata},
    )


def _tool(rows, current_ids=None, statuses=None, user=USER):
    tools_dict = {}
    entry = add_attachments_tool(
        tools_dict, attachments=rows, current_ids=current_ids or [], user_id=user
    )
    if statuses:
        entry["config"]["statuses"] = statuses
    return AttachmentsTool(dict(entry["config"]))


class TestRegistration:
    def test_adds_a_synthetic_entry(self):
        tools_dict = {}
        entry = add_attachments_tool(
            tools_dict,
            attachments=[{"id": "a", "filename": "a.txt", "content": "big"}],
            current_ids=["a"],
            user_id=USER,
        )
        assert tools_dict[ATTACHMENTS_TOOL_ID] is entry
        assert entry["id"] == ATTACHMENTS_TOOL_ID
        names = {a["name"] for a in entry["actions"]}
        assert names == {"attachments_list", "attachments_read", "attachments_search"}
        # The tool reads text from Postgres; config never carries it.
        assert "content" not in entry["config"]["attachments"][0]

    def test_tool_is_internal(self):
        assert AttachmentsTool.internal is True


class TestList:
    def test_lists_refs_and_status(self, pg_conn):
        a = _make(pg_conn, "a.txt", "alpha " * 10)
        b = _make(pg_conn, "b.txt", "beta " * 10)
        tool = _tool([a, b], current_ids=[str(b["id"])], statuses={"F1": "tool", "F2": "inline"})
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_list")
        assert 'ref="F1"' in out and 'name="a.txt"' in out
        assert 'ref="F2"' in out and 'name="b.txt"' in out
        assert "in_context" in out and "not_in_context" in out


class TestRead:
    def test_reads_a_slice_with_next_offset(self, pg_conn):
        content = "".join(f"line {i}\n" for i in range(5000))
        a = _make(pg_conn, "a.txt", content)
        tool = _tool([a])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="F1", offset=100, max_tokens=500)
        assert '<file_content ref="F1"' in out
        body = out.split(">", 2)[1]
        assert content[100:160] in body
        assert "offset=" in out
        assert "not instructions" in out

    def test_reads_to_the_end(self, pg_conn):
        a = _make(pg_conn, "a.txt", "short text")
        tool = _tool([a])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="f1")
        assert "short text" in out
        assert "end of F1" in out

    def test_offset_past_the_end(self, pg_conn):
        a = _make(pg_conn, "a.txt", "short text")
        tool = _tool([a])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="F1", offset=500)
        assert "past the end" in out

    def test_accepts_filename_as_ref(self, pg_conn):
        a = _make(pg_conn, "notes.txt", "hello world")
        tool = _tool([a])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="notes.txt")
        assert "hello world" in out

    def test_unknown_ref(self, pg_conn):
        a = _make(pg_conn, "a.txt", "hello")
        tool = _tool([a])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="F9")
        assert "No attachment" in out and "F1" in out

    def test_another_users_attachment_is_refused(self, pg_conn):
        theirs = _make(pg_conn, "secret.txt", "top secret", user="someone-else")
        # Even if a foreign row slipped into the config, reads are scoped to
        # the caller in SQL.
        tool = _tool([theirs])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="F1")
        assert "top secret" not in out

    def test_earlier_turn_attachment_is_readable(self, pg_conn):
        # Turn 0 uploaded F1; on turn 2 only F2 is current, F1 still resolves.
        first = _make(pg_conn, "first.txt", "from the first turn")
        second = _make(pg_conn, "second.txt", "from this turn")
        earlier = {k: v for k, v in first.items() if k != "content"}
        tool = _tool([earlier, second], current_ids=[str(second["id"])])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="F1")
        assert "from the first turn" in out

    def test_file_without_text(self, pg_conn):
        repo = AttachmentsRepository(pg_conn)
        scan = repo.create(
            USER,
            "scan.pdf",
            "/uploads/scan.pdf",
            mime_type="application/pdf",
            content="",
            token_count=0,
            metadata={"extraction": {"status": "no_text"}},
        )
        tool = _tool([scan])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_read", ref="F1")
        assert "no extractable text" in out


class TestSearch:
    def test_keyword_search_returns_ref_scoped_snippets(self, pg_conn):
        a = _make(pg_conn, "a.txt", ("filler text " * 300) + "the quokka lives on Rottnest island. " + ("more " * 300))
        b = _make(pg_conn, "b.txt", "nothing to see here " * 50)
        tool = _tool([a, b])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_search", query="quokka island")
        assert 'ref="F1"' in out
        assert "quokka" in out
        assert 'ref="F2"' not in out
        assert "offset=" in out
        assert tool.retrieved_docs and tool.retrieved_docs[0]["title"] == "a.txt"

    def test_search_can_be_limited_to_refs(self, pg_conn):
        a = _make(pg_conn, "a.txt", "apples and pears")
        b = _make(pg_conn, "b.txt", "apples and plums")
        tool = _tool([a, b])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_search", query="apples", refs=["F2"])
        assert 'ref="F2"' in out
        assert 'ref="F1"' not in out

    def test_no_hits(self, pg_conn):
        a = _make(pg_conn, "a.txt", "apples and pears")
        tool = _tool([a])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_search", query="zeppelin")
        assert "No matches" in out

    def test_semantic_results_for_indexed_files(self, pg_conn):
        a = _make(
            pg_conn,
            "a.txt",
            "alpha beta gamma",
            index={"status": "done", "source_id": "11111111-1111-1111-1111-111111111111"},
        )
        tool = _tool([a])

        class _Doc(str):
            def __new__(cls, text, metadata):
                obj = str.__new__(cls, text)
                obj.page_content = text
                obj.metadata = metadata
                return obj

        class _Store:
            def search(self, query, k):
                return [_Doc("beta gamma", {"offset": 6})]

        with _patch_db(pg_conn), patch(
            "docsgpt.agents.tools.attachments._store_for_source", lambda sid: _Store()
        ):
            out = tool.execute_action("attachments_search", query="meaning of beta")
        assert 'ref="F1"' in out
        assert 'offset="6"' in out

    def test_requires_a_query(self, pg_conn):
        a = _make(pg_conn, "a.txt", "apples")
        tool = _tool([a])
        with _patch_db(pg_conn):
            out = tool.execute_action("attachments_search", query="  ")
        assert "Error" in out


@pytest.mark.parametrize("action", ["attachments_read", "attachments_search"])
def test_tool_without_attachments(action):
    tool = AttachmentsTool({"attachments": [], "user_id": USER})
    out = tool.execute_action(action, ref="F1", query="x")
    assert "no attachments" in out.lower()
