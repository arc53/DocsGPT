"""Tests for MonitorsRepository and the schedule queries that must leave monitors out."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository


def _conversation(conn, user_id: str = "u1") -> str:
    return str(ConversationsRepository(conn).create(user_id, "chat")["id"])


def _create(repo, conversation_id, **overrides):
    now = datetime.now(timezone.utc)
    fields = {
        "user_id": "u1",
        "conversation_id": conversation_id,
        "agent_id": None,
        "description": "BTC below $50k",
        "source_type": "webpage",
        "spec": {"source": {"type": "webpage", "url": "https://example.com"}},
        "on_match": "tell me the price",
        "end_at": now + timedelta(days=7),
        "next_run_at": now + timedelta(minutes=15),
        "max_wakes": 1,
        "interval_seconds": 900,
        "state": {"hash": "abc"},
    }
    fields.update(overrides)
    return repo.create(**fields)


class TestCreateAndRead:
    def test_create_joins_the_schedule(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn), approval={"tool_id": "t1", "args_hash": "h", "required": True})
        assert row["id"] == row["schedule_id"]
        assert row["status"] == "active"
        assert row["on_match"] == "tell me the price"
        assert row["monitor_state"] == {"hash": "abc"}
        assert row["approval"]["tool_id"] == "t1"
        schedule = SchedulesRepository(pg_conn).get_internal(row["id"])
        assert schedule["trigger_type"] == "monitor"
        assert schedule["tool_allowlist"] == ["t1"]

    def test_a_call_that_needs_no_approval_is_not_allowlisted(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn), approval={"tool_id": "t1", "args_hash": "h", "required": False})
        assert SchedulesRepository(pg_conn).get_internal(row["id"])["tool_allowlist"] == []

    def test_get_is_owner_scoped(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn))
        assert repo.get(row["id"], "u1") is not None
        assert repo.get(row["id"], "u2") is None
        assert repo.get("not-a-uuid", "u1") is None

    def test_list_filters_by_status_and_conversation(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        conv_a, conv_b = _conversation(pg_conn), _conversation(pg_conn)
        a = _create(repo, conv_a)
        _create(repo, conv_b)
        repo.finish(a["id"], "cancelled")
        assert len(repo.list_for_user("u1")) == 2
        assert [r["conversation_id"] for r in repo.list_for_user("u1", statuses=["active"])] == [conv_b]
        assert [r["id"] for r in repo.list_for_user("u1", conversation_id=conv_a)] == [a["id"]]
        assert repo.list_for_user("u2") == []
        assert repo.count_live_for_user("u1") == 1

    def test_find_ingest_monitors(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        conv = _conversation(pg_conn)
        row = _create(
            repo, conv, source_type="ingest", spec={"source": {"type": "ingest", "source_id": "s-1"}}
        )
        assert [r["id"] for r in repo.find_ingest_monitors("u1", "s-1")] == [row["id"]]
        assert repo.find_ingest_monitors("u1", "s-2") == []
        assert repo.find_ingest_monitors("u2", "s-1") == []


class TestLifecycle:
    def test_finish_drops_the_approval_and_only_changes_live_monitors(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn), approval={"tool_id": "t1"})
        assert repo.finish(row["id"], "cancelled") is True
        again = repo.get_internal(row["id"])
        assert again["status"] == "cancelled" and again["approval"] is None and again["next_run_at"] is None
        assert SchedulesRepository(pg_conn).get_internal(row["id"])["tool_allowlist"] == []
        assert repo.finish(row["id"], "completed") is False

    def test_pause_keeps_the_approval_and_resume_clears_errors(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn), approval={"tool_id": "t1"})
        repo.update(row["id"], {"last_error": "boom", "unreachable_since": datetime.now(timezone.utc)})
        repo.bump_failures(row["id"])
        assert repo.finish(row["id"], "paused", reason="unreachable") is True
        paused = repo.get_internal(row["id"])
        assert paused["status"] == "paused" and paused["paused_reason"] == "unreachable"
        assert paused["approval"] == {"tool_id": "t1"}
        nxt = datetime.now(timezone.utc) + timedelta(minutes=1)
        assert repo.resume(row["id"], nxt) is True
        resumed = repo.get_internal(row["id"])
        assert resumed["status"] == "active" and resumed["consecutive_failure_count"] == 0
        assert resumed["last_error"] is None and resumed["unreachable_since"] is None
        assert repo.resume(row["id"], nxt) is False

    def test_resume_refuses_an_expired_monitor(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn), end_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        repo.finish(row["id"], "paused")
        assert repo.resume(row["id"], None) is False

    def test_counters(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn))
        assert repo.add_wake(row["id"], datetime.now(timezone.utc)) == 1
        assert repo.add_wake(row["id"], datetime.now(timezone.utc)) == 2
        assert repo.add_judge_tokens(row["id"], 120) == 120
        assert repo.bump_failures(row["id"]) == 1
        repo.update(row["id"], {"monitor_state": {"seen": ["a\x00b"]}, "not_a_column": 1})
        assert repo.get_internal(row["id"])["monitor_state"] == {"seen": ["ab"]}

    def test_tick_lease_excludes_a_second_tick(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        row = _create(repo, _conversation(pg_conn))
        assert repo.acquire_tick(row["id"], stale_seconds=600) is True
        assert repo.acquire_tick(row["id"], stale_seconds=600) is False
        pg_conn.execute(
            text("UPDATE monitors SET tick_started_at = now() - interval '20 minutes' WHERE schedule_id = :id"),
            {"id": row["id"]},
        )
        assert repo.acquire_tick(row["id"], stale_seconds=600) is True
        repo.release_tick(row["id"])
        assert repo.acquire_tick(row["id"], stale_seconds=600) is True

    def test_conversation_delete_cascades_the_monitor_row(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        conv = _conversation(pg_conn)
        row = _create(repo, conv)
        pg_conn.execute(text("DELETE FROM conversations WHERE id = CAST(:id AS uuid)"), {"id": conv})
        assert repo.get_internal(row["id"]) is None
        # The schedule goes with it, so nothing is left counting against the cap.
        assert SchedulesRepository(pg_conn).get_internal(row["id"]) is None
        assert repo.count_live_for_user("u1") == 0

    def test_lock_user_is_reentrant_within_a_transaction(self, pg_conn):
        repo = MonitorsRepository(pg_conn)
        repo.lock_user("u1")
        repo.lock_user("u1")


class TestSchedulesLeaveMonitorsOut:
    def test_counts_and_agent_listing_skip_monitors(self, pg_conn):
        conv = _conversation(pg_conn)
        _create(MonitorsRepository(pg_conn), conv)
        schedules = SchedulesRepository(pg_conn)
        assert schedules.count_active_for_user("u1") == 0
        agent = pg_conn.execute(
            text("INSERT INTO agents (user_id, name, status) VALUES ('u1', 'a', 'draft') RETURNING id")
        ).scalar()
        _create(MonitorsRepository(pg_conn), conv, agent_id=str(agent))
        assert schedules.list_for_agent(str(agent), "u1") == []
        assert len(schedules.list_for_agent(str(agent), "u1", trigger_type="monitor")) == 1

    def test_the_schedule_dispatcher_never_claims_a_monitor(self, pg_conn):
        conv = _conversation(pg_conn)
        _create(MonitorsRepository(pg_conn), conv, next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        assert SchedulesRepository(pg_conn).list_due() == []
