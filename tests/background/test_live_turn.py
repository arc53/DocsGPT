"""A continuation turn's message is written as it runs, so the chat can show, resume and stop it."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import text

from docsgpt.background import continuation, live_turn, wake
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


@pytest.fixture()
def quiet(monkeypatch):
    """No Celery, notifications or Redis: record what would go out instead."""
    sent = {"events": [], "notified": [], "continued": []}
    monkeypatch.setattr(wake, "schedule_continuation", lambda *a, **kw: None)
    monkeypatch.setattr(continuation, "publish_conversation_continued", lambda *a: sent["continued"].append(a))
    monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: sent["notified"].append(kw))
    monkeypatch.setattr(
        "docsgpt.events.publisher.publish_user_event",
        lambda user, kind, payload, **kw: sent["events"].append((kind, payload["message_id"])),
    )
    monkeypatch.setattr(live_turn, "stop_requested", lambda message_id: False)
    monkeypatch.setattr(live_turn, "clear_stop", lambda message_id: None)
    return sent


def _queue(conversation_id):
    wake.wake_conversation(user_id="u1", conversation_id=conversation_id, source="monitor", ref_id="m",
                           title="page changed", body="b", payload=None, dedupe_key="k1")


def _row(engine, message_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, response, message_metadata FROM conversation_messages WHERE id = CAST(:id AS uuid)"),
            {"id": message_id},
        ).fetchone()
    return row._mapping if row is not None else None


def _journal(engine, message_id):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT event_type, payload FROM message_events WHERE message_id = CAST(:id AS uuid) "
                 "ORDER BY sequence_no"),
            {"id": message_id},
        ).fetchall()
    return [(r.event_type, r.payload) for r in rows]


def _outcome(answer, **extra):
    return {"answer": answer, "thought": "", "sources": [], "tool_calls": [], "model_id": "m-1", **extra}


def _install(monkeypatch, body):
    seen = {}

    def fake_run(conversation, messages, wakes, *, message_id, live=None, **kwargs):
        seen["message_id"] = message_id
        seen["live"] = live
        return body(message_id, live)

    monkeypatch.setattr(continuation, "_run_turn", fake_run)
    return seen


class TestLiveContinuation:
    def test_the_message_streams_while_the_turn_runs(self, bg_db, conversation, quiet, monkeypatch):
        conversation_id, _ = conversation
        during = {}

        def body(message_id, live):
            live.event({"thought": "reading"})
            live.event({"answer": "The page "})
            live.event({"answer": "changed."})
            live._journal.flush()
            during["row"] = _row(bg_db, message_id)
            during["journal"] = _journal(bg_db, message_id)
            return _outcome("The page changed.")

        seen = _install(monkeypatch, body)
        _queue(conversation_id)
        summary = continuation.continue_conversation_body(conversation_id, 0)

        assert summary["state"] == "delivered"
        message_id = seen["message_id"]
        assert during["row"]["status"] == "streaming"
        # The chat shows the event it answers from the start, never as the user's words.
        assert during["row"]["message_metadata"]["wake"]["dedupe_key"] == "k1"
        assert [t for t, _ in during["journal"]] == ["thought", "answer", "answer"]
        final = _row(bg_db, message_id)
        assert final["status"] == "complete" and final["response"] == "The page changed."
        assert _journal(bg_db, message_id)[-1][0] == "end"
        assert quiet["events"] == [("message.started", message_id), ("message.finished", message_id)]
        assert quiet["notified"] and quiet["continued"]

    def test_a_silent_turn_never_shows_its_no_reply_and_leaves_no_message(self, bg_db, conversation, quiet,
                                                                         monkeypatch):
        conversation_id, _ = conversation
        during = {}

        def body(message_id, live):
            for chunk in ("NO", "_RE", "PLY", "."):
                live.event({"answer": chunk})
            live._journal.flush()
            during["journal"] = _journal(bg_db, message_id)
            return _outcome("NO_REPLY.")

        seen = _install(monkeypatch, body)
        _queue(conversation_id)
        assert continuation.continue_conversation_body(conversation_id, 0)["state"] == "suppressed"
        assert during["journal"] == []
        assert _row(bg_db, seen["message_id"]) is None
        assert quiet["notified"] == [] and quiet["continued"] == []

    def test_text_that_only_starts_like_no_reply_is_sent(self, bg_db, conversation, quiet, monkeypatch):
        conversation_id, _ = conversation
        during = {}

        def body(message_id, live):
            live.event({"answer": "No"})
            live.event({"answer": "thing changed"})
            live._journal.flush()
            during["journal"] = _journal(bg_db, message_id)
            return _outcome("Nothing changed")

        _install(monkeypatch, body)
        _queue(conversation_id)
        continuation.continue_conversation_body(conversation_id, 0)
        # Held while it could have been NO_REPLY, then sent as one chunk.
        assert [p["answer"] for t, p in during["journal"] if t == "answer"] == ["Nothing changed"]

    def test_a_failed_turn_takes_its_message_back_out(self, bg_db, conversation, quiet, monkeypatch):
        conversation_id, _ = conversation

        def body(message_id, live):
            raise RuntimeError("provider down")

        seen = _install(monkeypatch, body)
        _queue(conversation_id)
        assert continuation.continue_conversation_body(conversation_id, 0)["state"] == "failed"
        assert _row(bg_db, seen["message_id"]) is None
        assert quiet["events"][-1][0] == "message.finished"

    def test_the_users_stop_reaches_the_turn(self, bg_db, conversation, quiet, monkeypatch):
        monkeypatch.setattr(live_turn, "STOP_POLL_SECONDS", 0.01)
        requested = set()
        monkeypatch.setattr(live_turn, "stop_requested", lambda message_id: message_id in requested)
        stopped_jobs = []
        monkeypatch.setattr("docsgpt.background.service.stop_turn_jobs", lambda *a: stopped_jobs.append(a))
        conversation_id, _ = conversation

        def body(message_id, live):
            live.event({"answer": "Half an "})
            requested.add(message_id)
            deadline = time.monotonic() + 5
            while not live.stopped() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert live.stopped()
            return _outcome("Half an ", stopped=True)

        seen = _install(monkeypatch, body)
        _queue(conversation_id)
        summary = continuation.continue_conversation_body(conversation_id, 0)

        message_id = seen["message_id"]
        assert summary["state"] == "stopped"
        assert _row(bg_db, message_id)["status"] == "complete"
        assert _row(bg_db, message_id)["response"] == "Half an "
        assert stopped_jobs == [(conversation_id, message_id, "u1")]
        # Stopped by the user, who is looking at it: no notification, no further turn.
        assert quiet["notified"] == []

    def test_a_stop_before_any_text_is_saved_as_stopped(self, bg_db, conversation, quiet, monkeypatch):
        monkeypatch.setattr("docsgpt.background.service.stop_turn_jobs", lambda *a: None)
        conversation_id, _ = conversation
        seen = _install(monkeypatch, lambda message_id, live: _outcome("", stopped=True))
        _queue(conversation_id)
        assert continuation.continue_conversation_body(conversation_id, 0)["state"] == "stopped"
        row = _row(bg_db, seen["message_id"])
        assert row["status"] == "failed"
        assert row["message_metadata"]["error_code"] == "stopped"
        assert _journal(bg_db, seen["message_id"])[-1] == (
            "error", {"type": "error", "error": "Stopped before any response was produced.", "code": "stopped"}
        )

    def test_a_message_removed_by_the_user_keeps_the_results_for_them(self, bg_db, conversation, quiet,
                                                                     monkeypatch):
        conversation_id, _ = conversation

        def body(message_id, live):
            with bg_db.begin() as conn:
                ConversationsRepository(conn).delete_in_flight_message(message_id)
            return _outcome("Too late.")

        _install(monkeypatch, body)
        _queue(conversation_id)
        assert continuation.continue_conversation_body(conversation_id, 0)["state"] == "superseded_by_user"
        with bg_db.connect() as conn:
            status = conn.execute(text("SELECT status FROM conversation_wakes WHERE dedupe_key = 'k1'")).scalar()
        assert status == "failed"

    def test_a_failed_save_takes_the_row_out_and_keeps_the_results(self, bg_db, conversation, quiet, monkeypatch):
        monkeypatch.setattr(
            live_turn.LiveTurn, "finish", lambda self, *a, **kw: live_turn.MessageUpdateOutcome.INVALID
        )
        conversation_id, _ = conversation
        seen = _install(monkeypatch, lambda message_id, live: _outcome("Lost."))
        _queue(conversation_id)
        assert continuation.continue_conversation_body(conversation_id, 0)["state"] == "failed"
        assert _row(bg_db, seen["message_id"]) is None
        with bg_db.connect() as conn:
            status = conn.execute(text("SELECT status FROM conversation_wakes WHERE dedupe_key = 'k1'")).scalar()
        assert status == "failed"

    def test_without_a_row_the_message_is_appended_at_the_end(self, bg_db, conversation, quiet, monkeypatch):
        monkeypatch.setattr(live_turn.LiveTurn, "open", classmethod(lambda cls, *a, **kw: None))
        conversation_id, _ = conversation
        seen = _install(monkeypatch, lambda message_id, live: _outcome("Appended."))
        _queue(conversation_id)
        assert continuation.continue_conversation_body(conversation_id, 0)["state"] == "delivered"
        assert seen["live"] is None
        assert _row(bg_db, seen["message_id"])["response"] == "Appended."


class _Broken:
    def __enter__(self):
        raise RuntimeError("db down")

    def __exit__(self, *exc):
        return False


def _conversation_row(bg_db, conversation_id):
    with bg_db.connect() as conn:
        return dict(conn.execute(
            text("SELECT id, user_id FROM conversations WHERE id = CAST(:c AS uuid)"), {"c": conversation_id}
        ).fetchone()._mapping)


class TestLiveTurnUnit:
    def test_it_journals_each_kind_of_event_as_the_chat_stream_sends_it(self, bg_db, conversation, quiet):
        import uuid

        conversation_id, _ = conversation
        message_id = str(uuid.uuid4())
        turn = live_turn.LiveTurn.open(_conversation_row(bg_db, conversation_id), message_id, prompt="p",
                                       metadata={"wake": {"source": "job"}})
        turn.event({"answer": "N"})
        turn.event({"type": "tool_call", "data": {"call_id": "c1", "status": "pending"}})
        turn.event({"sources": [{"title": "t", "text": "x" * 300}, "raw"]})
        turn.event({"tool_calls": [{"call_id": "c1", "status": "completed"}]})
        turn.event({"metadata": {"ignored": True}})
        result = turn.finish(_outcome("Nope", model_id="m-2"), metadata={"continuation": True})
        turn.event({"answer": "after the end"})

        assert result is live_turn.MessageUpdateOutcome.UPDATED
        journal = _journal(bg_db, message_id)
        # The held "N" goes out once a tool call shows the turn is doing something.
        assert [t for t, _ in journal] == ["answer", "tool_call", "source", "tool_calls", "end"]
        assert journal[2][1]["source"][0]["text"] == "x" * 100 + "..."
        assert journal[2][1]["source"][1] == "raw"

    def test_a_row_it_cannot_reserve_leaves_the_append_to_the_caller(self, bg_db, conversation, quiet, monkeypatch):
        monkeypatch.setattr(live_turn, "db_session", _Broken)
        conversation_id, _ = conversation
        assert live_turn.LiveTurn.open(_conversation_row(bg_db, conversation_id), "m", prompt="p", metadata={}) is None
        assert quiet["events"] == []

    def test_a_save_that_fails_still_ends_the_turn(self, bg_db, conversation, quiet, monkeypatch):
        import uuid

        conversation_id, _ = conversation
        message_id = str(uuid.uuid4())
        turn = live_turn.LiveTurn.open(_conversation_row(bg_db, conversation_id), message_id, prompt="p", metadata={})
        real_session = live_turn.db_session
        database = {"down": True}
        monkeypatch.setattr(live_turn, "db_session", lambda: _Broken() if database["down"] else real_session())
        result = turn.finish(_outcome("x"), metadata={})
        assert result is live_turn.MessageUpdateOutcome.INVALID
        assert quiet["events"] == [("message.started", message_id), ("message.finished", message_id)]
        # Once the database is back, discarding takes the half-written row out.
        database["down"] = False
        turn.discard()
        assert _row(bg_db, message_id) is None

    def test_the_ticker_keeps_the_row_alive(self, bg_db, conversation, quiet, monkeypatch):
        import uuid

        monkeypatch.setattr(live_turn, "STOP_POLL_SECONDS", 0.01)
        monkeypatch.setattr(live_turn, "HEARTBEAT_SECONDS", 0)
        beats = []
        monkeypatch.setattr(
            live_turn.ConversationsRepository, "heartbeat_message", lambda self, message_id: beats.append(message_id)
        )
        conversation_id, _ = conversation
        message_id = str(uuid.uuid4())
        turn = live_turn.LiveTurn.open(_conversation_row(bg_db, conversation_id), message_id, prompt="p", metadata={})
        deadline = time.monotonic() + 5
        while len(beats) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        turn.discard()
        assert len(beats) >= 3

    def test_a_failed_publish_does_not_fail_the_turn(self, bg_db, conversation, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("redis down")

        monkeypatch.setattr("docsgpt.events.publisher.publish_user_event", _boom)
        monkeypatch.setattr(live_turn, "clear_stop", lambda message_id: None)
        monkeypatch.setattr(live_turn, "stop_requested", lambda message_id: False)
        import uuid

        conversation_id, _ = conversation
        turn = live_turn.LiveTurn.open(_conversation_row(bg_db, conversation_id), str(uuid.uuid4()), prompt="p",
                                       metadata={})
        assert turn is not None
        turn.discard()


def test_repositories_ignore_ids_that_are_not_uuids(pg_conn):
    from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository

    assert BackgroundJobsRepository(pg_conn).list_for_message("nope", "nope", "u1") == []
    assert ConversationsRepository(pg_conn).delete_in_flight_message("nope") is False


class TestBudgetContinuation:
    def test_time_limit_saves_failed_partial_answer(self, bg_db, conversation, quiet, monkeypatch):
        def body(message_id, live):
            live.event({"answer": "Saved progress"})
            return _outcome("Saved progress", error_type="TimeLimit", error="Stopped: time limit.")

        seen = _install(monkeypatch, body)
        _queue(conversation[0])
        result = continuation.continue_conversation_body(conversation[0])
        row = _row(bg_db, seen["message_id"])
        assert result["state"] == "failed"
        assert row["status"] == "failed"
        assert row["response"] == "Saved progress"
        assert row["message_metadata"]["error_code"] == "time_limit"
        assert _journal(bg_db, seen["message_id"])[-1] == (
            "error", {"type": "error", "error": "Stopped: time limit.", "code": "time_limit"}
        )

    def test_time_limit_still_schedules_the_remaining_wakes(self, bg_db, conversation, quiet, monkeypatch):
        rest = []
        monkeypatch.setattr(continuation, "_schedule_rest", rest.append)
        _install(monkeypatch, lambda mid, live: _outcome("Partial", error_type="TimeLimit", error="Stopped: time limit."))
        _queue(conversation[0])
        assert continuation.continue_conversation_body(conversation[0])["state"] == "failed"
        assert rest == [conversation[0]]

    def test_a_failed_deferral_keeps_the_saved_round(self, bg_db, conversation, quiet, monkeypatch):
        def broken(*args):
            raise RuntimeError("broker down")

        monkeypatch.setattr(continuation, "defer_round", broken)
        seen = _install(monkeypatch, lambda mid, live: _outcome("Progress", budget_deferred=True))
        _queue(conversation[0])
        assert continuation.continue_conversation_body(conversation[0])["state"] == "deferred"
        assert _row(bg_db, seen["message_id"])["status"] == "complete"

    def test_round_saves_then_defers_once(self, bg_db, conversation, quiet, monkeypatch):
        scheduled = []
        monkeypatch.setattr(wake, "schedule_continuation", lambda *a, **kw: scheduled.append((a, kw)))
        seen = _install(monkeypatch, lambda mid, live: _outcome("Progress", budget_deferred=True))
        _queue(conversation[0])
        scheduled.clear()
        result = continuation.continue_conversation_body(conversation[0])
        assert result["state"] == "deferred"
        assert _row(bg_db, seen["message_id"])["status"] == "complete"
        assert len(scheduled) == 1
        with bg_db.connect() as conn:
            pending = conn.execute(text("SELECT dedupe_key FROM conversation_wakes WHERE status = 'pending'"))
            assert [r[0] for r in pending] == [f"round:{seen['message_id']}"]

    def test_outer_time_limit_preserves_already_streamed_text(self, bg_db, conversation, quiet, monkeypatch):
        from celery.exceptions import SoftTimeLimitExceeded

        def body(message_id, live):
            live.event({"answer": "Saved before runner returned"})
            raise SoftTimeLimitExceeded()

        seen = _install(monkeypatch, body)
        _queue(conversation[0])
        result = continuation.continue_conversation_body(conversation[0])
        row = _row(bg_db, seen["message_id"])
        assert result["state"] == "failed"
        assert row["status"] == "failed"
        assert row["response"] == "Saved before runner returned"
