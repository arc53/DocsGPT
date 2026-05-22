"""Tests for the SchedulerTool."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

# Pre-import to stabilise the ToolManager.load_tools walk's import order
# (avoids the mcp_tool ↔ application.api.user circular when ToolManager
# instantiation is the first reachable importer in a test process).
import application.api.user.tools.mcp  # noqa: F401

from application.agents.tools.scheduler import SchedulerTool  # noqa: E402
from application.core.settings import settings  # noqa: E402
from application.storage.db.repositories.schedules import SchedulesRepository  # noqa: E402


@pytest.fixture
def patch_sessions(pg_conn):
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        yield pg_conn

    with patch(
        "application.agents.tools.scheduler.db_session", _ctx,
    ), patch(
        "application.agents.tools.scheduler.db_readonly", _ctx,
    ):
        yield


def _make_agent(conn, user_id: str = "u1") -> str:
    row = conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status) "
            "VALUES (:u, 'a', 'draft') RETURNING id"
        ),
        {"u": user_id},
    ).fetchone()
    return str(row[0])


def _make_tool(name="scheduler", *, user_id="u1", agent_id=None, conversation_id=None):
    return SchedulerTool(
        tool_config={
            "agent_id": agent_id,
            "conversation_id": conversation_id,
        },
        user_id=user_id,
    )


class TestGuards:
    def test_requires_user_id(self):
        tool = SchedulerTool(tool_config={"agent_id": str(uuid.uuid4())})
        assert "user_id" in tool.execute_action("schedule_task", instruction="x")

    def test_rejects_invalid_agent_id(self):
        tool = _make_tool(user_id="u1", agent_id="not-a-uuid")
        assert "invalid agent_id" in tool.execute_action(
            "schedule_task", instruction="x"
        )

    def test_requires_agent_or_conversation(self):
        # Neither agent_id nor conversation_id → hard error (webhook caller
        # outside any chat); scheduler can't operate without a conversation home.
        tool = _make_tool(user_id="u1", agent_id=None, conversation_id=None)
        out = tool.execute_action("schedule_task", instruction="x")
        assert "conversation_id" in out or "conversation home" in out


class TestScheduleTask:
    def test_creates_with_delay(self, pg_conn, patch_sessions):
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id, conversation_id=None)
        out = tool.execute_action(
            "schedule_task", instruction="say hi", delay="2h",
        )
        parsed = json.loads(out)
        assert "task_id" in parsed
        assert "resolved_run_at" in parsed
        row = SchedulesRepository(pg_conn).get(parsed["task_id"], "u1")
        assert row is not None
        assert row["trigger_type"] == "once"
        assert row["created_via"] == "chat"
        fire = datetime.fromisoformat(parsed["resolved_run_at"].replace("Z", "+00:00"))
        delta = fire - datetime.now(timezone.utc)
        assert timedelta(minutes=119) <= delta <= timedelta(minutes=121)

    def test_creates_with_run_at(self, pg_conn, patch_sessions):
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        fire = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        out = tool.execute_action(
            "schedule_task", instruction="x", run_at=fire,
        )
        parsed = json.loads(out)
        assert "task_id" in parsed

    def test_rejects_both_delay_and_run_at(self, pg_conn, patch_sessions):
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        out = tool.execute_action(
            "schedule_task", instruction="x", delay="30m",
            run_at="2030-01-01T00:00:00Z",
        )
        assert "only one" in out

    def test_rejects_past_run_at(self, pg_conn, patch_sessions):
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        out = tool.execute_action("schedule_task", instruction="x", run_at=past)
        assert "past" in out

    def test_rejects_beyond_horizon(
        self, pg_conn, patch_sessions, monkeypatch
    ):
        monkeypatch.setattr(settings, "SCHEDULE_ONCE_MAX_HORIZON", 3600)
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        far = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
        out = tool.execute_action("schedule_task", instruction="x", run_at=far)
        assert "horizon" in out


class TestQuota:
    def test_quota_enforced(self, pg_conn, patch_sessions, monkeypatch):
        monkeypatch.setattr(settings, "SCHEDULE_MAX_PER_USER", 2)
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        for _ in range(2):
            out = tool.execute_action(
                "schedule_task", instruction="x", delay="1h",
            )
            assert "task_id" in out
        out = tool.execute_action(
            "schedule_task", instruction="x", delay="1h",
        )
        assert "maximum" in out


class TestListAndCancel:
    def test_list_returns_pending(self, pg_conn, patch_sessions):
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        for _ in range(3):
            tool.execute_action(
                "schedule_task", instruction="x", delay="1h",
            )
        listed = json.loads(tool.execute_action("list_scheduled_tasks"))
        assert len(listed["tasks"]) == 3
        assert all(t["status"] == "active" for t in listed["tasks"])

    def test_cancel_flips_status(self, pg_conn, patch_sessions):
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        created = json.loads(
            tool.execute_action("schedule_task", instruction="x", delay="1h")
        )
        out = tool.execute_action(
            "cancel_scheduled_task", task_id=created["task_id"]
        )
        assert "cancelled" in out
        row = SchedulesRepository(pg_conn).get(created["task_id"], "u1")
        assert row["status"] == "cancelled"

    def test_cancel_unknown_id_rejected(self, pg_conn, patch_sessions):
        agent_id = _make_agent(pg_conn)
        tool = _make_tool(user_id="u1", agent_id=agent_id)
        out = tool.execute_action(
            "cancel_scheduled_task", task_id="not-a-uuid",
        )
        assert "valid id" in out


class TestActionsMetadata:
    def test_actions_listed(self):
        tool = SchedulerTool()
        names = {a["name"] for a in tool.get_actions_metadata()}
        assert names == {
            "schedule_task", "list_scheduled_tasks", "cancel_scheduled_task",
        }


class TestAgentlessInvocation:
    def test_agentless_creates_schedule_with_null_agent_id(
        self, pg_conn, patch_sessions,
    ):
        """Agentless chat → scheduler.schedule_task → row with NULL agent_id."""
        conv_id = pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'origin') RETURNING id"
            )
        ).fetchone()[0]
        tool = _make_tool(
            user_id="u1", agent_id=None, conversation_id=str(conv_id),
        )
        out = tool.execute_action(
            "schedule_task", instruction="ping me later", delay="1h",
        )
        parsed = json.loads(out)
        assert "task_id" in parsed
        row = SchedulesRepository(pg_conn).get(parsed["task_id"], "u1")
        assert row is not None
        assert row["agent_id"] is None
        assert row["trigger_type"] == "once"
        assert row["created_via"] == "chat"
        assert str(row["origin_conversation_id"]) == str(conv_id)

    def test_agentless_list_scoped_to_conversation(
        self, pg_conn, patch_sessions,
    ):
        """Agentless list_scheduled_tasks scopes to user + origin conversation."""
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
        tool_a = _make_tool(
            user_id="u1", agent_id=None, conversation_id=str(conv_a),
        )
        tool_b = _make_tool(
            user_id="u1", agent_id=None, conversation_id=str(conv_b),
        )
        tool_a.execute_action(
            "schedule_task", instruction="in-a", delay="1h",
        )
        tool_a.execute_action(
            "schedule_task", instruction="in-a-2", delay="2h",
        )
        tool_b.execute_action(
            "schedule_task", instruction="in-b", delay="3h",
        )
        listed_a = json.loads(tool_a.execute_action("list_scheduled_tasks"))
        listed_b = json.loads(tool_b.execute_action("list_scheduled_tasks"))
        assert len(listed_a["tasks"]) == 2
        assert len(listed_b["tasks"]) == 1
        assert all(t["status"] == "active" for t in listed_a["tasks"])

    def test_agentless_cancel_blocked_for_other_conversation(
        self, pg_conn, patch_sessions,
    ):
        """A user can't cancel tasks created in another agentless chat."""
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
        tool_a = _make_tool(
            user_id="u1", agent_id=None, conversation_id=str(conv_a),
        )
        tool_b = _make_tool(
            user_id="u1", agent_id=None, conversation_id=str(conv_b),
        )
        created = json.loads(
            tool_a.execute_action(
                "schedule_task", instruction="x", delay="1h",
            )
        )
        out = tool_b.execute_action(
            "cancel_scheduled_task", task_id=created["task_id"],
        )
        assert "not found" in out

    def test_agentless_cancel_succeeds_in_own_conversation(
        self, pg_conn, patch_sessions,
    ):
        conv = pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'a') RETURNING id"
            )
        ).fetchone()[0]
        tool = _make_tool(
            user_id="u1", agent_id=None, conversation_id=str(conv),
        )
        created = json.loads(
            tool.execute_action("schedule_task", instruction="x", delay="1h")
        )
        out = tool.execute_action(
            "cancel_scheduled_task", task_id=created["task_id"],
        )
        assert "cancelled" in out

    def test_agentless_snapshot_allowlist_lists_user_tools(
        self, pg_conn, patch_sessions,
    ):
        """Agentless schedule captures the user's non-approval tools at fire-time."""
        from application.agents.tools.scheduler import _safe_default_allowlist
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        # Seed an explicit non-approval user tool.
        user_tool = UserToolsRepository(pg_conn).create(
            "u1", "read_webpage", config={}, actions=[
                {"name": "fetch", "active": True, "require_approval": False},
            ], status=True,
        )
        conv = pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'a') RETURNING id"
            )
        ).fetchone()[0]
        tool = _make_tool(
            user_id="u1", agent_id=None, conversation_id=str(conv),
        )
        out = tool.execute_action(
            "schedule_task", instruction="x", delay="1h",
        )
        parsed = json.loads(out)
        row = SchedulesRepository(pg_conn).get(parsed["task_id"], "u1")
        # The explicit user_tools row is in the snapshot (approval=False).
        assert str(user_tool["id"]) in (row["tool_allowlist"] or [])
        # Direct allowlist call returns the same set.
        ids = _safe_default_allowlist(None, "u1")
        assert str(user_tool["id"]) in ids


class TestAllowlistSnapshotSemantics:
    """The schedule's ``tool_allowlist`` is a **pre-auth snapshot**, not a
    visibility cap. The LLM sees the user's *current* tools at fire time
    (via ``ToolExecutor._get_user_tools``); the snapshot only governs
    whether an approval-gated tool can run unattended."""

    def test_tool_added_after_creation_is_visible_at_fire_time(
        self, pg_conn, patch_sessions,
    ):
        """Schedule captures the allowlist at creation; a tool added later is
        visible at fire time (resolver re-queries) but isn't in the snapshot."""
        from application.agents.tools.scheduler import _safe_default_allowlist
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        pg_conn.execute(
            text(
                "INSERT INTO conversations (user_id, name) "
                "VALUES ('u1', 'snap-add') RETURNING id"
            )
        ).fetchone()
        # Snapshot the allowlist BEFORE adding the new tool.
        snapshot_before = _safe_default_allowlist(None, "u1")

        # User adds an approval-gated tool AFTER schedule creation.
        added = UserToolsRepository(pg_conn).create(
            "u1", "telegram",
            config={}, actions=[
                {"name": "send", "active": True, "require_approval": True},
            ], status=True,
        )

        # The snapshot does NOT include the post-creation tool.
        assert str(added["id"]) not in snapshot_before
        # …but the LLM sees it at fire time (current resolver state).
        snapshot_after = _safe_default_allowlist(None, "u1")
        # An approval-gated tool is excluded from the snapshot regardless,
        # but it IS in ``list_active_for_user`` (what the LLM's tool_executor
        # uses) — make that explicit:
        ids_now = {
            str(r["id"]) for r in
            UserToolsRepository(pg_conn).list_active_for_user("u1")
        }
        assert str(added["id"]) in ids_now
        # And approval-gated still skipped from the safe allowlist.
        assert str(added["id"]) not in snapshot_after

    def test_tool_deleted_between_creation_and_fire_is_invisible(
        self, pg_conn, patch_sessions,
    ):
        """A tool deleted between schedule creation and fire is gone for the
        LLM at fire time (the resolver lists the current state)."""
        from application.agents.tools.scheduler import _safe_default_allowlist
        from application.storage.db.repositories.user_tools import (
            UserToolsRepository,
        )

        repo = UserToolsRepository(pg_conn)
        existing = repo.create(
            "u1", "read_webpage",
            config={}, actions=[
                {"name": "fetch", "active": True, "require_approval": False},
            ], status=True,
        )
        # Snapshot at creation includes it (non-approval).
        snapshot = _safe_default_allowlist(None, "u1")
        assert str(existing["id"]) in snapshot

        # User deletes it; fire-time resolver no longer surfaces it.
        repo.delete(str(existing["id"]), "u1")
        ids_now = {r["id"] for r in repo.list_active_for_user("u1")}
        assert str(existing["id"]) not in ids_now
        # And the freshly-recomputed allowlist drops it too.
        snapshot_after = _safe_default_allowlist(None, "u1")
        assert str(existing["id"]) not in snapshot_after


class TestInternalFlag:
    def test_internal_true(self):
        assert SchedulerTool.internal is True

    def test_not_in_tool_manager_auto_load(self):
        from application.agents.tools.tool_manager import ToolManager

        tm = ToolManager(config={})
        assert "scheduler" not in tm.tools

    def test_load_tool_special_case_still_works(self):
        from application.agents.tools.tool_manager import ToolManager

        tm = ToolManager(config={})
        tool = tm.load_tool(
            "scheduler",
            tool_config={"agent_id": str(uuid.uuid4())},
            user_id="u1",
        )
        assert isinstance(tool, SchedulerTool)
        assert tool.user_id == "u1"
