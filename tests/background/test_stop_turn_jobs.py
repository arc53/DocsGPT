"""Stopping a turn stops the jobs it handed off, so none of them resumes the chat."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.background import jobs, service, wake
from docsgpt.background.context import BackgroundContext
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversation_wakes import ConversationWakesRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


def _context(conversation_id, message_id):
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = True
    return context


def _job(conversation_id, message_id, call_id="c1"):
    row, _ = jobs.create_job(
        _context(conversation_id, message_id),
        tool_name="artifact_generator",
        action_name="create_artifact",
        journal_key=f"{message_id}:{call_id}",
        arguments={},
    )
    return row


def _record_entry(bg_db, message_id, job_id):
    with bg_db.begin() as conn:
        ConversationsRepository(conn).update_message_by_id(
            message_id, {"tool_calls": [{"call_id": "c1", "status": "pending", "job_id": str(job_id)}]}
        )


def _row(bg_db, job_id):
    with bg_db.connect() as conn:
        return BackgroundJobsRepository(conn).get(str(job_id))


def _entry(bg_db, message_id):
    with bg_db.connect() as conn:
        return conn.execute(
            text("SELECT tool_calls FROM conversation_messages WHERE id = CAST(:id AS uuid)"), {"id": message_id}
        ).fetchone()[0][0]


def test_a_working_job_is_cancelled_and_never_wakes_the_chat(bg_db, conversation, monkeypatch):
    monkeypatch.setattr(jobs, "publish_job_updated", lambda row: None)
    monkeypatch.setattr(service, "publish_job_updated", lambda row: None)
    monkeypatch.setattr(wake.settings, "AUTO_RESUME_ENABLED", True)
    woken = []
    monkeypatch.setattr(wake, "wake_conversation", lambda **kw: woken.append(kw))
    conversation_id, message_id = conversation
    job = _job(conversation_id, message_id)
    _record_entry(bg_db, message_id, job["id"])

    assert service.stop_turn_jobs(conversation_id, message_id, "u1") == 1
    done = jobs.complete_from_tool(job["id"], tool=object(), action_name="create_artifact", parameters={}, value="ok")

    assert done["status"] == "cancelled"
    assert woken == []
    assert _row(bg_db, job["id"])["delivery_state"] == "suppressed"
    assert _entry(bg_db, message_id)["job_status"] == "cancelled"


def test_a_job_that_finished_before_the_stop_has_its_wake_withdrawn(bg_db, conversation, monkeypatch):
    monkeypatch.setattr(jobs, "publish_job_updated", lambda row: None)
    monkeypatch.setattr(jobs, "_deliver", lambda row: None)
    conversation_id, message_id = conversation
    job = _job(conversation_id, message_id)
    jobs.finalize(job["id"], status="completed", result={"text": "done", "artifact_id": "art-1"})
    with bg_db.begin() as conn:
        wakes = ConversationWakesRepository(conn)
        wakes.enqueue(
            user_id="u1", conversation_id=conversation_id, source="job", ref_id=str(job["id"]),
            title="t", body="b", payload={}, dedupe_key=f"job:{job['id']}:final",
        )
    # The stopped turn's message gets its entry when it is finalized, after the job ended.
    _record_entry(bg_db, message_id, job["id"])

    assert service.stop_turn_jobs(conversation_id, message_id, "u1") == 1

    assert _row(bg_db, job["id"])["delivery_state"] == "suppressed"
    with bg_db.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM conversation_wakes WHERE ref_id = :r"), {"r": str(job["id"])}
        ).scalar()
    assert status == "superseded"
    entry = _entry(bg_db, message_id)
    assert entry["job_status"] == "completed" and entry["artifact_id"] == "art-1"


def test_jobs_of_other_turns_and_users_are_left_alone(bg_db, conversation, monkeypatch):
    monkeypatch.setattr(jobs, "publish_job_updated", lambda row: None)
    monkeypatch.setattr(service, "publish_job_updated", lambda row: None)
    conversation_id, message_id = conversation
    with bg_db.begin() as conn:
        other_message = ConversationsRepository(conn).append_message(conversation_id, {"prompt": "q", "response": ""})
    other = _job(conversation_id, str(other_message["id"]), call_id="c2")

    assert service.stop_turn_jobs(conversation_id, message_id, "u1") == 0
    assert service.stop_turn_jobs(conversation_id, str(other_message["id"]), "someone-else") == 0
    assert _row(bg_db, other["id"])["cancel_requested_at"] is None


def test_a_job_that_ended_mid_stream_shows_on_the_saved_message(bg_db, conversation, monkeypatch):
    """The job finished before its turn saved the entry; once saved, the entry takes the outcome."""
    monkeypatch.setattr(jobs, "publish_job_updated", lambda row: None)
    monkeypatch.setattr(jobs, "_deliver", lambda row: None)
    conversation_id, message_id = conversation
    job = _job(conversation_id, message_id)
    running = _job(conversation_id, message_id, call_id="c2")
    jobs.finalize(job["id"], status="completed", result={"text": "done", "artifact_id": "art-1"})
    _record_entry(bg_db, message_id, job["id"])

    assert service.show_finished_jobs(conversation_id, message_id, "u1") == 1

    entry = _entry(bg_db, message_id)
    assert entry["job_status"] == "completed" and entry["artifact_id"] == "art-1"
    # Showing an outcome is not delivering it: the wake still runs.
    assert _row(bg_db, job["id"])["delivery_state"] == "pending"
    assert _row(bg_db, running["id"])["status"] == "working"
