"""Tests for the background-job beat sweeps."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.background import jobs, reconciler, sandbox_runner
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

    def test_a_stale_sandbox_job_is_polled_again(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        polls = []
        monkeypatch.setattr(sandbox_runner, "_enqueue_poll", lambda job_id, countdown: polls.append(job_id))
        conversation_id, message_id = conversation
        row = _job(conversation_id, message_id, runner="sandbox")
        _set(bg_db, row["id"], "heartbeat_at = now() - interval '5 minutes'")
        summary = reconciler.sweep()
        assert summary["lost"] == 0
        assert summary["revived"] == 1
        assert polls == [row["id"]]
        revived = _get(bg_db, row["id"])
        assert revived["status"] == "working"
        assert revived["attempts"] == 1
        # The revive stamped the heartbeat: the next tick leaves it alone.
        assert reconciler.sweep()["revived"] == 0

    def test_a_sandbox_job_revived_too_often_is_lost(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        monkeypatch.setattr(sandbox_runner, "_enqueue_poll", lambda job_id, countdown: None)
        stopped = []
        monkeypatch.setattr(sandbox_runner, "cancel_detached", stopped.append)
        conversation_id, message_id = conversation
        row = _job(conversation_id, message_id, runner="sandbox")
        _set(bg_db, row["id"], f"attempts = {sandbox_runner.MAX_REVIVES}, heartbeat_at = now() - interval '5 minutes'")
        assert reconciler.sweep()["lost"] == 1
        assert _get(bg_db, row["id"])["status"] == "lost"
        assert [r["id"] for r in stopped] == [row["id"]]

    def test_a_queued_celery_job_gets_longer_before_it_is_lost(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        conversation_id, message_id = conversation
        row = _job(conversation_id, message_id, runner="celery")
        assert row["lease_owner"] is None
        _set(bg_db, row["id"], "heartbeat_at = now() - interval '5 minutes'")
        assert reconciler.sweep()["lost"] == 0
        _set(bg_db, row["id"], "heartbeat_at = now() - interval '20 minutes'")
        assert reconciler.sweep()["lost"] == 1

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
