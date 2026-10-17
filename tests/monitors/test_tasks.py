"""Tests for the beat-side helpers: the dispatcher hook never breaks the schedule beat, and hit retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.monitors import tasks
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerHitsRepository, TriggerLinksRepository


def test_dispatch_is_skipped_when_monitors_are_off(monkeypatch):
    monkeypatch.setattr(settings, "MONITORS_ENABLED", False)
    monkeypatch.setattr("docsgpt.monitors.tick.dispatch_due_monitors", lambda: {"ticked": 9})
    assert tasks.dispatch_monitors_safely() == {}


def test_dispatch_failure_is_contained(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("docsgpt.monitors.tick.dispatch_due_monitors", boom)
    assert tasks.dispatch_monitors_safely() == {"error": 1}


def test_dispatch_returns_the_pass_counts(monkeypatch):
    monkeypatch.setattr("docsgpt.monitors.tick.dispatch_due_monitors", lambda: {"ticked": 2})
    assert tasks.dispatch_monitors_safely() == {"ticked": 2}


def test_the_schedule_beat_runs_the_monitor_pass(monkeypatch):
    from docsgpt.api.user import tasks as user_tasks

    monkeypatch.setattr("docsgpt.api.user.scheduler_dispatcher.dispatch_due_runs", lambda: {"enqueued": 1})
    monkeypatch.setattr("docsgpt.monitors.tasks.dispatch_monitors_safely", lambda: {"ticked": 3})
    assert user_tasks.dispatch_scheduled_runs.run() == {"enqueued": 1, "monitors": {"ticked": 3}}


def test_cleanup_deletes_only_old_settled_hits(mon_db, conversation_id):
    now = datetime.now(timezone.utc)
    with mon_db.begin() as conn:
        monitor = MonitorsRepository(conn).create(
            user_id="u1",
            conversation_id=conversation_id,
            agent_id=None,
            description="d",
            source_type="webhook",
            spec={"source": {"type": "webhook"}},
            on_match="x",
            end_at=now + timedelta(days=1),
            next_run_at=now + timedelta(days=1),
            max_wakes=1,
        )
        link = TriggerLinksRepository(conn).create(
            monitor_id=monitor["id"],
            user_id="u1",
            conversation_id=conversation_id,
            token_hash="h",
            kind="webhook",
            expires_at=now + timedelta(days=1),
            max_hits=10,
        )
        hits = TriggerHitsRepository(conn)
        old_done = hits.insert(str(link["id"]), "a", {})
        old_pending = hits.insert(str(link["id"]), "b", {})
        fresh_done = hits.insert(str(link["id"]), "c", {})
        hits.mark(str(old_done["id"]), "processed")
        hits.mark(str(fresh_done["id"]), "processed")
        conn.execute(
            text("UPDATE trigger_hits SET received_at = now() - interval '30 days' WHERE dedupe_key IN ('a', 'b')")
        )
    assert tasks.cleanup_hits()["deleted"] == 1
    with mon_db.connect() as conn:
        left = {r[0] for r in conn.execute(text("SELECT dedupe_key FROM trigger_hits"))}
    assert left == {"b", "c"} and old_pending is not None
