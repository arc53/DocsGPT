"""Tests for the background-job beat sweeps."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.background import jobs, reconciler
from docsgpt.background.context import BackgroundContext
from docsgpt.background.results import LOST_NOTE
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository


def _job(conversation_id, message_id, key="k", **kwargs):
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = True
    row, _ = jobs.create_job(context, tool_name="t", action_name="a", journal_key=key, arguments={}, **kwargs)
    return row


def _set(engine, job_id, sql):
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE background_jobs SET {sql} WHERE id = CAST(:id AS uuid)"), {"id": job_id})


def _get(engine, job_id):
    with engine.connect() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


class TestSweep:
    def test_a_stale_lease_is_lost_and_delivered(self, bg_db, conversation, monkeypatch):
        delivered = []
        monkeypatch.setattr(jobs, "_deliver", delivered.append)
        conversation_id, message_id = conversation
        stale = _job(conversation_id, message_id, key="a")
        fresh = _job(conversation_id, message_id, key="b")
        _set(bg_db, stale["id"], "heartbeat_at = now() - interval '5 minutes'")
        summary = reconciler.sweep()
        assert summary["lost"] == 1
        lost = _get(bg_db, stale["id"])
        assert lost["status"] == "lost"
        assert lost["error"]["message"] == LOST_NOTE
        assert _get(bg_db, fresh["id"])["status"] == "working"
        assert [row["id"] for row in delivered] == [stale["id"]]

    def test_a_sandbox_job_is_not_lost_by_its_heartbeat(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row = _job(conversation_id, message_id, runner="sandbox")
        _set(bg_db, row["id"], "heartbeat_at = now() - interval '5 minutes'")
        assert reconciler.sweep()["lost"] == 0
        assert _get(bg_db, row["id"])["status"] == "working"

    def test_a_job_past_its_deadline_fails(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row = _job(conversation_id, message_id)
        _set(bg_db, row["id"], "deadline_at = now() - interval '5 minutes'")
        assert reconciler.sweep()["timed_out"] == 1
        failed = _get(bg_db, row["id"])
        assert failed["status"] == "failed"
        assert failed["error"]["type"] == "TimeoutError"


class TestCleanup:
    def test_deletes_expired_jobs(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row = _job(conversation_id, message_id)
        jobs.finalize(row["id"], status="completed", result={"text": "x"})
        _set(bg_db, row["id"], "expires_at = now() - interval '1 minute'")
        assert reconciler.cleanup()["jobs"] == 1
        assert _get(bg_db, row["id"]) is None
