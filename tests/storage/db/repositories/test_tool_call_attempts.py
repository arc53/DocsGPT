"""Tests for ToolCallAttemptsRepository against a real Postgres instance."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.storage.db.repositories.tool_call_attempts import (
    ToolCallAttemptsRepository,
)


def _repo(conn) -> ToolCallAttemptsRepository:
    return ToolCallAttemptsRepository(conn)


class TestNulSafety:
    """Postgres jsonb rejects \\u0000; a NUL-laden tool result must not
    lose the attempt row (07-17 PDF incident)."""

    def test_record_proposed_strips_nul_from_arguments(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.record_proposed(
            "call-nul-1", "read_webpage", "read_webpage",
            {"url": "https://x\x00.example"},
            user_id="u1",
        )
        row = pg_conn.execute(
            text(
                "SELECT arguments FROM tool_call_attempts "
                "WHERE call_id = 'call-nul-1'"
            )
        ).fetchone()
        assert dict(row._mapping)["arguments"] == {"url": "https://x.example"}

    def test_mark_executed_strips_nul_from_result(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.record_proposed(
            "call-nul-2", "read_webpage", "read_webpage", {}, user_id="u1",
        )
        assert repo.mark_executed(
            "call-nul-2", "pdf\x00garbage\x00text", user_id="u1",
        )
        row = pg_conn.execute(
            text(
                "SELECT status, result FROM tool_call_attempts "
                "WHERE call_id = 'call-nul-2'"
            )
        ).fetchone()
        mapping = dict(row._mapping)
        assert mapping["status"] == "confirmed"  # no message_id → confirmed
        assert mapping["result"]["result"] == "pdfgarbagetext"

    def test_upsert_executed_strips_nul_from_result(self, pg_conn):
        repo = _repo(pg_conn)
        repo.upsert_executed(
            "call-nul-3", "read_webpage", "read_webpage",
            {"q": "a\x00b"}, "res\x00ult",
            user_id="u1",
        )
        row = pg_conn.execute(
            text(
                "SELECT arguments, result FROM tool_call_attempts "
                "WHERE call_id = 'call-nul-3'"
            )
        ).fetchone()
        mapping = dict(row._mapping)
        assert mapping["arguments"] == {"q": "ab"}
        assert mapping["result"]["result"] == "result"


def _message(conn) -> str:
    from docsgpt.storage.db.repositories.conversations import ConversationsRepository

    repo = ConversationsRepository(conn)
    conv = repo.create("u1", "c")
    return str(repo.append_message(str(conv["id"]), {"prompt": "p", "response": "r"})["id"])


class TestAppResult:
    RESULT = {"content": [], "structuredContent": {"elements": []}, "isError": False}

    def test_round_trip(self, pg_conn):
        repo = _repo(pg_conn)
        mid = _message(pg_conn)
        assert repo.record_proposed(f"{mid}:c1", "mcp_tool", "create_view", {}, message_id=mid, user_id="u1")
        assert repo.mark_executed(f"{mid}:c1", "ok", message_id=mid, user_id="u1", app_result=self.RESULT)

        assert repo.get_app_result(mid, "c1") == self.RESULT

    def test_upsert_keeps_it_too(self, pg_conn):
        repo = _repo(pg_conn)
        mid = _message(pg_conn)
        repo.upsert_executed(
            f"{mid}:c1", "mcp_tool", "create_view", {}, "ok", message_id=mid, user_id="u1", app_result=self.RESULT
        )

        assert repo.get_app_result(mid, "c1") == self.RESULT

    def test_wrong_ids_or_no_view_find_nothing(self, pg_conn):
        repo = _repo(pg_conn)
        mid, other = _message(pg_conn), _message(pg_conn)
        repo.record_proposed(f"{mid}:c1", "mcp_tool", "create_view", {}, message_id=mid, user_id="u1")
        repo.mark_executed(f"{mid}:c1", "ok", message_id=mid, user_id="u1", app_result=self.RESULT)
        repo.record_proposed(f"{mid}:c2", "mcp_tool", "read_me", {}, message_id=mid, user_id="u1")
        repo.mark_executed(f"{mid}:c2", "ok", message_id=mid, user_id="u1")

        assert repo.get_app_result(mid, "c9") is None
        assert repo.get_app_result(other, "c1") is None
        assert repo.get_app_result(mid, "c2") is None
