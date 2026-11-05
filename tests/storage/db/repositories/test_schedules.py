"""Tests for SchedulesRepository against an ephemeral Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from docsgpt.storage.db.repositories.schedules import SchedulesRepository


def _insert_agent(conn, user_id: str = "u1") -> str:
    row = conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status) "
            "VALUES (:u, 'a', 'draft') RETURNING id"
        ),
        {"u": user_id},
    ).fetchone()
    return str(row[0])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestCreate:
    def test_create_once(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        run_at = _now() + timedelta(hours=1)
        row = repo.create(
            user_id="u1",
            agent_id=agent_id,
            trigger_type="once",
            instruction="summarize",
            run_at=run_at,
            next_run_at=run_at,
            timezone="Europe/Warsaw",
            tool_allowlist=["telegram"],
            origin_conversation_id=None,
        )
        assert row["trigger_type"] == "once"
        assert row["status"] == "active"
        assert row["tool_allowlist"] == ["telegram"]
        assert row["timezone"] == "Europe/Warsaw"

    def test_create_recurring(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        row = repo.create(
            user_id="u1",
            agent_id=agent_id,
            trigger_type="recurring",
            instruction="weekly digest",
            cron="0 9 * * 1",
            next_run_at=_now() + timedelta(days=1),
            timezone="Europe/Warsaw",
        )
        assert row["cron"] == "0 9 * * 1"
        assert row["trigger_type"] == "recurring"


class TestCreateAgentless:
    """Agentless schedules (migration 0011) carry NULL ``agent_id``."""

    def test_create_with_null_agent_id(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        conv_id = pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'origin') RETURNING id"
            )
        ).fetchone()[0]
        row = repo.create(
            user_id="u1",
            agent_id=None,
            trigger_type="once",
            instruction="agentless ping",
            run_at=_now() + timedelta(hours=1),
            next_run_at=_now() + timedelta(hours=1),
            origin_conversation_id=str(conv_id),
            created_via="chat",
        )
        assert row["agent_id"] is None
        assert row["trigger_type"] == "once"
        assert str(row["origin_conversation_id"]) == str(conv_id)

    def test_list_for_conversation_scopes_correctly(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        conv_a = pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'a') RETURNING id"
            )
        ).fetchone()[0]
        conv_b = pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'b') RETURNING id"
            )
        ).fetchone()[0]
        for _ in range(2):
            repo.create(
                user_id="u1", agent_id=None, trigger_type="once",
                instruction="x", run_at=_now() + timedelta(hours=1),
                origin_conversation_id=str(conv_a), created_via="chat",
            )
        repo.create(
            user_id="u1", agent_id=None, trigger_type="once",
            instruction="x", run_at=_now() + timedelta(hours=1),
            origin_conversation_id=str(conv_b), created_via="chat",
        )
        rows = repo.list_for_conversation("u1", str(conv_a))
        assert len(rows) == 2
        rows_other = repo.list_for_conversation("u1", str(conv_b))
        assert len(rows_other) == 1
        rows_other_user = repo.list_for_conversation("u-other", str(conv_a))
        assert rows_other_user == []

    def test_list_for_conversation_status_filter(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        conv_id = pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'a') RETURNING id"
            )
        ).fetchone()[0]
        active = repo.create(
            user_id="u1", agent_id=None, trigger_type="once",
            instruction="active", run_at=_now() + timedelta(hours=1),
            origin_conversation_id=str(conv_id), created_via="chat",
        )
        cancelled = repo.create(
            user_id="u1", agent_id=None, trigger_type="once",
            instruction="cancelled", run_at=_now() + timedelta(hours=1),
            origin_conversation_id=str(conv_id), created_via="chat",
        )
        repo.cancel(str(cancelled["id"]), "u1")
        rows = repo.list_for_conversation(
            "u1", str(conv_id), statuses=["active"],
        )
        assert [str(r["id"]) for r in rows] == [str(active["id"])]


class TestGet:
    def test_get_owned(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
        )
        fetched = repo.get(str(created["id"]), "u1")
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_other_user_blocked(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
        )
        assert repo.get(str(created["id"]), "u2") is None


class TestListForAgent:
    def test_filters_by_agent_and_user(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        a1 = _insert_agent(pg_conn, "u1")
        a2 = _insert_agent(pg_conn, "u1")
        for agent in (a1, a1, a2):
            repo.create(
                user_id="u1", agent_id=agent, trigger_type="once",
                instruction="i", run_at=_now() + timedelta(hours=1),
            )
        rows = repo.list_for_agent(a1, "u1")
        assert len(rows) == 2
        rows_other = repo.list_for_agent(a1, "u2")
        assert rows_other == []

    def test_status_filter(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
        )
        repo.update(str(created["id"]), "u1", {"status": "paused"})
        active = repo.list_for_agent(agent_id, "u1", statuses=["active"])
        assert active == []
        paused = repo.list_for_agent(agent_id, "u1", statuses=["paused"])
        assert len(paused) == 1


class TestListDue:
    def test_returns_due_active_only(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        due = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() - timedelta(seconds=10),
        )
        future = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(hours=1),
        )
        repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() - timedelta(minutes=1),
            status="paused",
        )
        rows = repo.list_due()
        ids = {r["id"] for r in rows}
        assert due["id"] in ids
        assert future["id"] not in ids
        assert all(r["status"] == "active" for r in rows)


class TestUpdateCancelFailureCounters:
    def test_update_fields(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="old", run_at=_now() + timedelta(hours=1),
        )
        updated = repo.update(str(created["id"]), "u1", {
            "instruction": "new", "tool_allowlist": ["a", "b"],
        })
        assert updated["instruction"] == "new"
        assert updated["tool_allowlist"] == ["a", "b"]

    def _stamped(self, pg_conn, **kw) -> tuple:
        """A recurring schedule whose ``plan_changed_at`` is a day old."""
        repo = SchedulesRepository(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=_insert_agent(pg_conn), trigger_type="recurring",
            instruction="i", cron="0 9 * * *", next_run_at=_now() + timedelta(hours=1), **kw,
        )
        old = _now() - timedelta(days=1)
        pg_conn.execute(
            text("UPDATE schedules SET plan_changed_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": old, "id": str(created["id"])},
        )
        return repo, str(created["id"]), old

    def test_a_new_schedule_has_a_plan_change_time(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=_insert_agent(pg_conn), trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
        )
        assert created["plan_changed_at"] is not None

    def test_a_timing_edit_moves_plan_changed_at(self, pg_conn):
        for field, value in (("cron", "0 10 * * *"), ("timezone", "Europe/Berlin"), ("run_at", _now())):
            repo, schedule_id, old = self._stamped(pg_conn)
            updated = repo.update(schedule_id, "u1", {field: value})
            assert datetime.fromisoformat(str(updated["plan_changed_at"])) > old, field

    def test_a_resume_moves_plan_changed_at(self, pg_conn):
        repo, schedule_id, old = self._stamped(pg_conn, status="paused")
        updated = repo.update(schedule_id, "u1", {"status": "active"})
        assert datetime.fromisoformat(str(updated["plan_changed_at"])) > old

    def test_resending_the_same_timing_keeps_plan_changed_at(self, pg_conn):
        # The edit form always sends the timezone, and may send the cron
        # it loaded; a rename must not wipe the calendar's missed slots.
        repo, schedule_id, old = self._stamped(pg_conn, timezone="Europe/Berlin")
        repo.update(
            schedule_id, "u1",
            {"name": "renamed", "cron": "0 9 * * *", "timezone": "Europe/Berlin", "run_at": None},
        )
        row = repo.get(schedule_id, "u1")
        assert datetime.fromisoformat(str(row["plan_changed_at"])) == old

    def test_setting_an_active_schedule_active_keeps_plan_changed_at(self, pg_conn):
        repo, schedule_id, old = self._stamped(pg_conn)
        repo.update(schedule_id, "u1", {"status": "active"})
        row = repo.get(schedule_id, "u1")
        assert datetime.fromisoformat(str(row["plan_changed_at"])) == old

    def test_other_writes_keep_plan_changed_at(self, pg_conn):
        repo, schedule_id, old = self._stamped(pg_conn)
        repo.update(schedule_id, "u1", {"name": "renamed", "status": "paused"})
        repo.update_internal(schedule_id, {"next_run_at": _now() + timedelta(days=1), "last_run_at": _now()})
        repo.bump_failure_count(schedule_id)
        row = repo.get(schedule_id, "u1")
        assert datetime.fromisoformat(str(row["plan_changed_at"])) == old

    def test_cancel_blocks_completed(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
        )
        repo.update_internal(str(created["id"]), {"status": "completed"})
        assert repo.cancel(str(created["id"]), "u1") is False
        assert repo.get(str(created["id"]), "u1")["status"] == "completed"

    def test_failure_counter_bump_and_reset(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(minutes=1),
        )
        assert repo.bump_failure_count(str(created["id"])) == 1
        assert repo.bump_failure_count(str(created["id"])) == 2
        repo.reset_failure_count(str(created["id"]))
        assert repo.get(str(created["id"]), "u1")["consecutive_failure_count"] == 0

    def test_autopause(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="recurring",
            instruction="i", cron="* * * * *",
            next_run_at=_now() + timedelta(minutes=1),
        )
        assert repo.autopause(str(created["id"])) is True
        assert repo.get(str(created["id"]), "u1")["status"] == "paused"
        assert repo.autopause(str(created["id"])) is False


class TestQuotaCount:
    def test_count_active_excludes_terminal(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        for _ in range(3):
            repo.create(
                user_id="u1", agent_id=agent_id, trigger_type="once",
                instruction="i", run_at=_now() + timedelta(hours=1),
            )
        completed = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
        )
        repo.update_internal(str(completed["id"]), {"status": "completed"})
        assert repo.count_active_for_user("u1") == 3


class TestDelete:
    def test_delete_scoped_to_user(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        agent_id = _insert_agent(pg_conn)
        created = repo.create(
            user_id="u1", agent_id=agent_id, trigger_type="once",
            instruction="i", run_at=_now() + timedelta(hours=1),
        )
        assert repo.delete(str(created["id"]), "u2") is False
        assert repo.delete(str(created["id"]), "u1") is True
        assert repo.get(str(created["id"]), "u1") is None


class TestListOwnedWithContext:
    def _conversation(self, conn, user_id: str = "u1", name: str = "Rotterdam market check") -> str:
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository

        return str(ConversationsRepository(conn).create(user_id, name)["id"])

    def test_spans_agents_and_agentless_with_names(self, pg_conn):
        repo = SchedulesRepository(pg_conn)
        a1 = _insert_agent(pg_conn)
        a2 = _insert_agent(pg_conn)
        pg_conn.execute(
            text("UPDATE agents SET name = 'Deal Desk' WHERE id = CAST(:id AS uuid)"), {"id": a1},
        )
        conv = self._conversation(pg_conn)
        repo.create("u1", a1, "recurring", "scan", cron="0 7 * * *", next_run_at=_now())
        repo.create("u1", a2, "once", "remind", run_at=_now(), next_run_at=_now())
        repo.create(
            "u1", None, "once", "chat task", run_at=_now(), next_run_at=_now(),
            origin_conversation_id=conv, created_via="chat",
        )
        rows = repo.list_owned_with_context("u1")
        assert len(rows) == 3
        by_instruction = {r["instruction"]: r for r in rows}
        assert by_instruction["scan"]["agent_name"] == "Deal Desk"
        assert by_instruction["chat task"]["agent_id"] is None
        assert by_instruction["chat task"]["agent_name"] is None
        assert by_instruction["chat task"]["origin_conversation_name"] == "Rotterdam market check"

    def test_leaves_out_monitors_and_other_users(self, pg_conn):
        from docsgpt.storage.db.repositories.monitors import MonitorsRepository

        repo = SchedulesRepository(pg_conn)
        conv = self._conversation(pg_conn)
        now = _now()
        MonitorsRepository(pg_conn).create(
            user_id="u1", conversation_id=conv, agent_id=None, description="BTC below $50k",
            source_type="webpage", spec={"source": {"type": "webpage", "url": "https://example.com"}},
            on_match="tell me", end_at=now + timedelta(days=7), next_run_at=now + timedelta(minutes=15),
            max_wakes=1, interval_seconds=900, state={"hash": "abc"},
        )
        repo.create("u2", _insert_agent(pg_conn, "u2"), "recurring", "theirs", cron="* * * * *")
        assert repo.list_owned_with_context("u1") == []

    def test_team_rows_leave_out_the_owners_chat_name(self, pg_conn):
        # A team editor reads these rows; the chat that created the schedule
        # is the owner's own and its title stays with them.
        repo = SchedulesRepository(pg_conn)
        agent = _insert_agent(pg_conn, "owner1")
        conv = self._conversation(pg_conn, user_id="owner1", name="Confidential deal")
        repo.create(
            "owner1", agent, "recurring", "weekly check", cron="0 9 * * 1",
            origin_conversation_id=conv, created_via="chat",
        )
        [team_row] = repo.list_for_agents_with_context([agent])
        assert team_row["instruction"] == "weekly check"
        assert team_row["origin_conversation_name"] is None
        [own_row] = repo.list_owned_with_context("owner1")
        assert own_row["origin_conversation_name"] == "Confidential deal"

    def _older_live_then_newer_finished(self, conn, agent=None, user_id="u1"):
        repo = SchedulesRepository(conn)
        live = repo.create(user_id, agent, "recurring", "weekly check", cron="0 9 * * 1")
        conn.execute(
            text("UPDATE schedules SET created_at = now() - interval '1 year' WHERE id = CAST(:id AS uuid)"),
            {"id": str(live["id"])},
        )
        for n in range(3):
            done = repo.create(user_id, agent, "once", f"reminder {n}", run_at=_now(), next_run_at=_now())
            conn.execute(
                text("UPDATE schedules SET status = 'completed' WHERE id = CAST(:id AS uuid)"),
                {"id": str(done["id"])},
            )
        return str(live["id"])

    def test_a_live_schedule_is_listed_past_newer_finished_ones(self, pg_conn):
        # Finished tasks are kept, so enough of them would fill the limit.
        live = self._older_live_then_newer_finished(pg_conn)
        rows = SchedulesRepository(pg_conn).list_owned_with_context("u1", limit=2)
        assert str(rows[0]["id"]) == live

    def test_a_team_agents_live_schedule_is_listed_past_newer_finished_ones(self, pg_conn):
        agent = _insert_agent(pg_conn, "owner1")
        live = self._older_live_then_newer_finished(pg_conn, agent, "owner1")
        rows = SchedulesRepository(pg_conn).list_for_agents_with_context([agent], limit=2)
        assert str(rows[0]["id"]) == live
