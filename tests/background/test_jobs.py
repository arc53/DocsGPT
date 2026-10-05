"""Tests for the job lifecycle against a real database."""

from __future__ import annotations

import json

from sqlalchemy import text

from docsgpt.background import jobs
from docsgpt.background.context import BackgroundContext
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.tool_call_attempts import ToolCallAttemptsRepository


def _context(conversation_id, message_id, auto_resume=True):
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = auto_resume
    return context


def _seed_turn(engine, message_id, *, job_id_entry=None):
    """Give the origin message a running tool-call entry and a proposed journal row."""
    with engine.begin() as conn:
        entries = [{"call_id": "c1", "status": "pending", "result": "running", "job_id": job_id_entry}]
        conn.execute(
            text("UPDATE conversation_messages SET tool_calls = CAST(:tc AS jsonb) WHERE id = CAST(:id AS uuid)"),
            {"tc": json.dumps(entries), "id": message_id},
        )
        ToolCallAttemptsRepository(conn).record_proposed(
            f"{message_id}:c1", "read_webpage", "read", {"url": "u"}, message_id=message_id, user_id="u1"
        )


def _job_row(engine, job_id):
    with engine.connect() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


def _journal(engine, key):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, result, error FROM tool_call_attempts WHERE call_id = :k"), {"k": key}
        ).fetchone()
    return row._mapping if row is not None else None


def _entry(engine, message_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT tool_calls FROM conversation_messages WHERE id = CAST(:id AS uuid)"), {"id": message_id}
        ).fetchone()[0][0]


class _Tool:
    def __init__(self):
        self.drained = False

    def get_artifact_id(self, action_name, **kwargs):
        return "art-1"

    def get_artifacts(self, action_name, **kwargs):
        return [{"id": "art-1", "filename": "out.csv", "ref": "A1"}]

    def drain_native_parts(self):
        self.drained = True
        return [{"label": "chart"}]


class TestCreate:
    def test_writes_a_redacted_working_job(self, bg_db, conversation, monkeypatch):
        published = []
        monkeypatch.setattr(jobs, "publish_job_updated", published.append)
        conversation_id, message_id = conversation
        row, created = jobs.create_job(
            _context(conversation_id, message_id),
            tool_name="code_executor",
            action_name="run_code",
            journal_key=f"{message_id}:c1",
            arguments={"code": "x" * 9000, "api_key": "sk-secret"},
        )
        assert created is True
        assert row["kind"] == "code_exec"
        assert row["args"]["api_key"] == "[REDACTED]"
        assert len(row["args"]["code"]) < 9000
        assert row["lease_owner"]
        assert row["auto_resume"] is True
        assert published and published[0]["id"] == row["id"]

    def test_caps(self, bg_db, conversation, monkeypatch):
        conversation_id, message_id = conversation
        context = _context(conversation_id, message_id)
        monkeypatch.setattr(jobs.settings, "BACKGROUND_MAX_JOBS_PER_CONVERSATION", 1)
        assert jobs.within_caps(context) is True
        jobs.create_job(context, tool_name="t", action_name="a", journal_key="k1", arguments={})
        assert jobs.within_caps(context) is False


class TestFinalize:
    def test_completed_call_settles_journal_and_entry(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row, _ = jobs.create_job(
            _context(conversation_id, message_id),
            tool_name="read_webpage",
            action_name="read",
            journal_key=f"{message_id}:c1",
            arguments={"url": "u"},
        )
        _seed_turn(bg_db, message_id, job_id_entry=row["id"])
        tool = _Tool()
        done = jobs.complete_from_tool(
            row["id"], tool=tool, action_name="read", parameters={}, value={"text": "page \x00body"}
        )
        assert done["status"] == "completed"
        assert done["result"]["status"] == "completed"
        assert "\x00" not in done["result"]["text"]
        assert done["result"]["artifacts"][0]["ref"] == "A1"
        assert tool.drained is True
        journal = _journal(bg_db, f"{message_id}:c1")
        assert journal["status"] == "confirmed"
        entry = _entry(bg_db, message_id)
        assert entry["status"] == "completed"
        assert entry["job_status"] == "completed"
        assert entry["artifact_id"] == "art-1"

    def test_in_band_error_fails_the_job(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row, _ = jobs.create_job(
            _context(conversation_id, message_id), tool_name="t", action_name="a", journal_key="k", arguments={}
        )
        done = jobs.complete_from_tool(
            row["id"], tool=object(), action_name="a", parameters={}, value={"status": "error", "error": "nope"}
        )
        assert done["status"] == "failed"
        assert done["result"]["status"] == "error"

    def test_exception_fails_the_job_and_the_journal(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row, _ = jobs.create_job(
            _context(conversation_id, message_id),
            tool_name="read_webpage",
            action_name="read",
            journal_key=f"{message_id}:c1",
            arguments={},
        )
        _seed_turn(bg_db, message_id, job_id_entry=row["id"])
        done = jobs.complete_from_tool(
            row["id"], tool=object(), action_name="read", parameters={}, error=TimeoutError("read timed out")
        )
        assert done["status"] == "failed"
        assert done["error"] == {"type": "TimeoutError", "message": "read timed out"}
        assert _journal(bg_db, f"{message_id}:c1")["status"] == "failed"
        assert _entry(bg_db, message_id)["status"] == "error"

    def test_a_requested_cancel_wins(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row, _ = jobs.create_job(
            _context(conversation_id, message_id), tool_name="t", action_name="a", journal_key="k", arguments={}
        )
        with bg_db.begin() as conn:
            BackgroundJobsRepository(conn).request_cancel(row["id"], "u1")
        done = jobs.complete_from_tool(row["id"], tool=object(), action_name="a", parameters={}, value="ok")
        assert done["status"] == "cancelled"
        assert done["result"]["text"] == "ok"

    def test_finishes_once_and_delivers_once(self, bg_db, conversation, monkeypatch):
        delivered = []
        monkeypatch.setattr(jobs, "_deliver", delivered.append)
        conversation_id, message_id = conversation
        row, _ = jobs.create_job(
            _context(conversation_id, message_id), tool_name="t", action_name="a", journal_key="k", arguments={}
        )
        assert jobs.finalize(row["id"], status="lost") is not None
        assert jobs.finalize(row["id"], status="completed", result={"text": "late"}) is None
        assert _job_row(bg_db, row["id"])["status"] == "lost"
        assert len(delivered) == 1


def test_a_cancel_that_lands_before_the_final_write_wins(bg_db, conversation, monkeypatch):
    """The cancel check is part of the final UPDATE, not a read before it."""
    monkeypatch.setattr(jobs, "_deliver", lambda row: None)
    conversation_id, message_id = conversation
    row, _ = jobs.create_job(
        _context(conversation_id, message_id), tool_name="t", action_name="a", journal_key="k", arguments={}
    )
    real_finish = BackgroundJobsRepository.finish

    def cancel_then_finish(self, job_id, **kwargs):
        with bg_db.begin() as conn:
            BackgroundJobsRepository(conn).request_cancel(job_id, "u1")
        return real_finish(self, job_id, **kwargs)

    monkeypatch.setattr(BackgroundJobsRepository, "finish", cancel_then_finish)
    done = jobs.finalize(row["id"], status="completed", result={"text": "ok"})
    assert done["status"] == "cancelled"
