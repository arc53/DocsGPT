"""Regression: scheduler stays out of the Add-Tool catalog but reaches the
agent picker, the LLM tool schema, and the schedules table on execute."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

# Pre-import to stabilise the ToolManager.load_tools walk's import order.
import application.api.user.tools.mcp  # noqa: F401

from application.agents.default_tools import (  # noqa: E402
    BUILTIN_AGENT_TOOLS,
    builtin_agent_tools_for_management,
    default_tool_id,
    resolve_tool_by_id,
)
from application.agents.tool_executor import ToolExecutor  # noqa: E402
from application.agents.tools.tool_manager import ToolManager  # noqa: E402
from application.storage.db.repositories.schedules import (  # noqa: E402
    SchedulesRepository,
)


@pytest.fixture
def patch_scheduler_sessions(pg_conn):
    """Redirect scheduler tool db session helpers to ``pg_conn``."""

    @contextmanager
    def _ctx():
        yield pg_conn

    with patch(
        "application.agents.tools.scheduler.db_session", _ctx,
    ), patch(
        "application.agents.tools.scheduler.db_readonly", _ctx,
    ):
        yield


def _make_agent(conn, *, user_id="alice", agent_tools=None) -> dict:
    """Insert an agents row whose tools JSONB carries agent_tools."""
    row = conn.execute(
        text(
            """
            INSERT INTO agents (user_id, name, status, key, tools)
            VALUES (:u, 'sched-agent', 'active', :k, CAST(:t AS jsonb))
            RETURNING *
            """
        ),
        {
            "u": user_id,
            "k": f"sk-{uuid.uuid4()}",
            "t": json.dumps(list(agent_tools or [])),
        },
    ).fetchone()
    return dict(row._mapping)


@pytest.mark.unit
class TestAddToolCatalogHidesScheduler:
    def test_tool_manager_walks_skip_internal_scheduler(self):
        tm = ToolManager(config={})
        assert "scheduler" not in tm.tools


@pytest.mark.unit
class TestAgentPickerExposesScheduler:
    def test_scheduler_is_listed_in_builtin_agent_tools(self):
        rows = builtin_agent_tools_for_management()
        assert any(r["name"] == "scheduler" for r in rows)
        assert "scheduler" in BUILTIN_AGENT_TOOLS

    def test_scheduler_row_is_flagged_builtin_not_default(self):
        scheduler_row = next(
            r for r in builtin_agent_tools_for_management()
            if r["name"] == "scheduler"
        )
        assert scheduler_row["builtin"] is True
        assert scheduler_row["default"] is False

    def test_synthetic_id_resolves_to_row_with_schedule_task_action(self):
        synthetic_id = default_tool_id("scheduler")
        row = resolve_tool_by_id(synthetic_id, "alice")
        assert row is not None
        assert row["name"] == "scheduler"
        action_names = {a["name"] for a in row.get("actions") or []}
        assert "schedule_task" in action_names


@pytest.mark.unit
class TestDualRegistration:
    """``scheduler`` is in both registries; same uuid5 resolves either way."""

    def test_scheduler_in_both_registries(self):
        from application.agents.default_tools import (
            BUILTIN_AGENT_TOOLS as BUILTINS,
            settings,
        )
        assert "scheduler" in BUILTINS
        assert "scheduler" in settings.DEFAULT_CHAT_TOOLS

    def test_same_synthetic_id_in_both_paths(self):
        from application.agents.default_tools import (
            builtin_agent_tool_ids,
            default_tool_ids,
        )
        via_default = default_tool_ids().get("scheduler")
        via_builtin = builtin_agent_tool_ids().get("scheduler")
        assert via_default == via_builtin
        assert via_default is not None

    def test_synthesized_default_tools_includes_scheduler(self):
        """Agentless chats see scheduler in the default-tools synthesis."""
        from application.agents.default_tools import synthesized_default_tools

        rows = synthesized_default_tools(None)
        names = {r["name"] for r in rows}
        assert "scheduler" in names

    def test_synthesized_builtin_agent_tools_includes_scheduler(self):
        """Agent picker still sees scheduler via the builtin registry."""
        from application.agents.default_tools import (
            builtin_agent_tools_for_management,
        )

        rows = builtin_agent_tools_for_management()
        names = {r["name"] for r in rows}
        assert "scheduler" in names


@pytest.mark.unit
class TestEndToEndAgentPickerToLLMSchema:
    def test_agent_with_scheduler_in_tools_exposes_schedule_task_to_llm(
        self, pg_conn,
    ):
        scheduler_id = default_tool_id("scheduler")
        agent = _make_agent(pg_conn, agent_tools=[scheduler_id])

        @contextmanager
        def _use_conn():
            yield pg_conn

        with patch("application.agents.tool_executor.db_readonly", _use_conn):
            executor = ToolExecutor(
                user_api_key=agent["key"], user="alice",
                agent_id=str(agent["id"]),
            )
            tools_dict = executor.get_tools()

        assert scheduler_id in tools_dict
        row = tools_dict[scheduler_id]
        assert row["name"] == "scheduler"

        schema = executor.prepare_tools_for_llm(tools_dict)
        function_names = {entry["function"]["name"] for entry in schema}
        assert "schedule_task" in function_names

    def test_executing_schedule_task_creates_one_time_schedule(
        self, pg_conn, patch_scheduler_sessions,
    ):
        agent = _make_agent(pg_conn)
        agent_id = str(agent["id"])
        user_id = "alice"

        tm = ToolManager(config={})
        tool = tm.load_tool(
            "scheduler",
            tool_config={"agent_id": agent_id, "conversation_id": None},
            user_id=user_id,
        )
        out = tool.execute_action(
            "schedule_task", instruction="ping me later", delay="1h",
        )
        parsed = json.loads(out)
        assert "task_id" in parsed

        row = SchedulesRepository(pg_conn).get(parsed["task_id"], user_id)
        assert row is not None
        assert row["trigger_type"] == "once"
        assert row["status"] == "active"
        assert row["created_via"] == "chat"
