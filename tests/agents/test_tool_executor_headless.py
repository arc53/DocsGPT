"""Headless mode + tool allowlist enforcement on ToolExecutor.check_pause."""

from __future__ import annotations

from types import SimpleNamespace

from application.agents.tool_executor import ToolExecutor


def _call(name: str, args: dict | None = None, call_id: str = "c1"):
    import json
    return SimpleNamespace(
        id=call_id,
        name=name,
        arguments=json.dumps(args or {}),
        thought_signature=None,
    )


def _executor(*, headless=False, allowlist=None):
    ex = ToolExecutor(headless=headless, tool_allowlist=allowlist or [])
    ex._name_to_tool = {
        "send": ("tool-a", "send"),
        "freecall": ("tool-b", "freecall"),
        "client_only": ("ct0", "client_only"),
    }
    return ex


def _tools_dict():
    return {
        "tool-a": {
            "id": "tool-a",
            "name": "telegram",
            "actions": [
                {"name": "send", "require_approval": True},
            ],
        },
        "tool-b": {
            "id": "tool-b",
            "name": "noop",
            "actions": [
                {"name": "freecall", "require_approval": False},
            ],
        },
        "ct0": {
            "name": "client_only",
            "client_side": True,
            "actions": [
                {"name": "client_only"},
            ],
        },
    }


class TestHeadlessApproval:
    def test_denied_when_not_in_allowlist(self):
        ex = _executor(headless=True, allowlist=[])
        result = ex.check_pause(_tools_dict(), _call("send"), "MockLLM")
        assert result is not None
        assert result["pause_type"] == "headless_denied"
        assert result["error_type"] == "tool_not_allowed"

    def test_allowed_when_in_allowlist(self):
        ex = _executor(headless=True, allowlist=["tool-a"])
        assert ex.check_pause(_tools_dict(), _call("send"), "MockLLM") is None

    def test_non_approval_tool_runs_freely(self):
        ex = _executor(headless=True, allowlist=[])
        assert ex.check_pause(_tools_dict(), _call("freecall"), "MockLLM") is None


class TestHeadlessClientSide:
    def test_client_side_always_denied_in_headless(self):
        # Client-side ignores the allowlist; no headless answer is possible.
        ex = _executor(headless=True, allowlist=["ct0"])
        result = ex.check_pause(_tools_dict(), _call("client_only"), "MockLLM")
        assert result is not None
        assert result["pause_type"] == "headless_denied"


class TestNormalModeUnchanged:
    def test_approval_still_pauses_without_headless(self):
        ex = _executor(headless=False)
        result = ex.check_pause(_tools_dict(), _call("send"), "MockLLM")
        assert result["pause_type"] == "awaiting_approval"

    def test_client_side_still_pauses_without_headless(self):
        ex = _executor(headless=False)
        result = ex.check_pause(_tools_dict(), _call("client_only"), "MockLLM")
        assert result["pause_type"] == "requires_client_execution"


# ---------------------------------------------------------------------------
# Scheduler exclusion in headless runs — chat-only tool must not appear in
# the toolset when a scheduled / webhook LLM runs, else it could re-schedule.
# ---------------------------------------------------------------------------
class TestHeadlessSchedulerExclusion:
    def test_synthesized_default_tools_drops_scheduler_in_headless(self):
        from application.agents.default_tools import (
            loaded_default_tools,
            synthesized_default_tools,
        )

        # Sanity: scheduler is on for normal chats…
        names_chat = {r["name"] for r in synthesized_default_tools(None)}
        if "scheduler" in loaded_default_tools():
            assert "scheduler" in names_chat
        # …and silently absent for headless runs.
        names_headless = {
            r["name"]
            for r in synthesized_default_tools(None, headless=True)
        }
        assert "scheduler" not in names_headless

    def test_get_user_tools_filters_scheduler_when_headless(
        self, monkeypatch,
    ):
        from application.agents import tool_executor as te_module
        from application.agents.default_tools import (
            default_tool_id,
            loaded_default_tools,
        )

        if "scheduler" not in loaded_default_tools():
            import pytest as _pytest  # local alias to keep top-of-module noise low
            _pytest.skip("scheduler not loaded in this env")

        # Stub the DB layer: no explicit user_tools so the synthesized
        # defaults are the only ``scheduler`` source — that path is what
        # this test pins.
        from contextlib import contextmanager

        @contextmanager
        def _fake_readonly():
            yield object()

        monkeypatch.setattr(te_module, "db_readonly", _fake_readonly)
        monkeypatch.setattr(
            te_module, "UserToolsRepository",
            lambda _c: type("R", (), {
                "list_active_for_user": lambda _self, _u: [],
            })(),
        )
        monkeypatch.setattr(
            te_module, "UsersRepository",
            lambda _c: type("R", (), {
                "get": lambda _self, _u: None,
            })(),
        )

        sched_id = default_tool_id("scheduler")

        ex_chat = te_module.ToolExecutor(headless=False)
        tools_chat = ex_chat._get_user_tools("u-test")
        assert sched_id in tools_chat

        ex_headless = te_module.ToolExecutor(headless=True)
        tools_headless = ex_headless._get_user_tools("u-test")
        assert sched_id not in tools_headless

    def test_get_tools_by_api_key_drops_scheduler_when_headless(
        self, monkeypatch,
    ):
        """An agent-bound headless run (e.g. webhook) skips scheduler even if
        the author added the synthetic id to ``agents.tools``."""
        from application.agents import tool_executor as te_module
        from application.agents.default_tools import default_tool_id

        sched_id = default_tool_id("scheduler")
        from contextlib import contextmanager

        @contextmanager
        def _fake_readonly():
            yield object()

        class _AgentsRepo:
            def __init__(self, _conn):
                pass

            def find_by_key(self, _k):
                return {"user_id": "u1", "tools": [sched_id]}

        class _UTRepo:
            def __init__(self, _conn):
                pass

            def get_any(self, _t, _u):
                return None

        monkeypatch.setattr(te_module, "db_readonly", _fake_readonly)
        monkeypatch.setattr(te_module, "AgentsRepository", _AgentsRepo)
        monkeypatch.setattr(te_module, "UserToolsRepository", _UTRepo)

        ex_normal = te_module.ToolExecutor(
            user_api_key="k", headless=False, agent_id="a",
        )
        tools_normal = ex_normal._get_tools_by_api_key("k")
        assert sched_id in tools_normal

        ex_headless = te_module.ToolExecutor(
            user_api_key="k", headless=True, agent_id="a",
        )
        tools_headless = ex_headless._get_tools_by_api_key("k")
        assert sched_id not in tools_headless
