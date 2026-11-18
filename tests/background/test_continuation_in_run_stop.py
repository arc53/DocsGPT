"""A continuation stopped by a limit mid-run fails like one refused before it started: its results stay deliverable.

The job results it was woken for are not marked delivered, so ``check_job`` or the user's next message still takes
them once there is allowance again; the half-written message is taken back out, and nothing says "time limit".
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from docsgpt.background import continuation, live_turn, wake

pytestmark = pytest.mark.fresh_db


@pytest.fixture()
def quiet(monkeypatch):
    """No Celery, notifications or Redis."""
    monkeypatch.setattr(wake, "schedule_continuation", lambda *a, **kw: None)
    monkeypatch.setattr(continuation, "publish_conversation_continued", lambda *a: None)
    monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: None)
    monkeypatch.setattr("docsgpt.events.publisher.publish_user_event", lambda *a, **kw: None)
    monkeypatch.setattr(live_turn, "stop_requested", lambda message_id: False)
    monkeypatch.setattr(live_turn, "clear_stop", lambda message_id: None)


def _queue(conversation_id):
    wake.wake_conversation(user_id="u1", conversation_id=conversation_id, source="monitor", ref_id="m",
                           title="page changed", body="b", payload=None, dedupe_key="k1")


def _install(monkeypatch, outcome):
    seen = {}

    def fake_run(conversation, messages, wakes, *, message_id, live=None, **kwargs):
        seen["message_id"] = message_id
        if live is not None:
            live.event({"answer": outcome["answer"]})
        return outcome

    monkeypatch.setattr(continuation, "_run_turn", fake_run)
    return seen


@pytest.mark.parametrize("error_type", ["payer_out_of_allowance", "budget_exceeded"])
def test_a_stop_mid_run_fails_and_keeps_the_results_deliverable(bg_db, conversation, quiet, monkeypatch, error_type):
    seen = _install(monkeypatch, {
        "answer": "Half of it", "thought": "", "sources": [], "tool_calls": [], "model_id": "m-1",
        "error_type": error_type, "error": "Usage quota reached.",
    })
    _queue(conversation[0])

    result = continuation.continue_conversation_body(conversation[0])

    assert result["state"] == "failed"
    assert result.get("error") != "TimeLimit"
    with bg_db.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM conversation_messages WHERE id = CAST(:id AS uuid)"), {"id": seen["message_id"]}
        ).fetchone()
        wakes = conn.execute(text("SELECT status FROM conversation_wakes")).fetchall()
    # The half-written message is taken back out, and the wake is failed, not delivered.
    assert row is None
    assert [w.status for w in wakes] == ["failed"]
