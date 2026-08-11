"""Tests for ToolCallAttemptsRepository against a real Postgres instance."""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.tool_call_attempts import (
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
