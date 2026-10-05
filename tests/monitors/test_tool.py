"""Tests for the monitor tool: its schema, its actions, and the approval hook in ToolExecutor."""

from __future__ import annotations

import json

import pytest

from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.agents.tools.monitor import MonitorTool
from docsgpt.llm.handlers.base import ToolCall
from docsgpt.monitors import service
from tests.monitors.helpers import executor_stub


class TestSchema:
    def test_actions_are_monitor_create_list_cancel(self):
        names = [action["name"] for action in MonitorTool().get_actions_metadata()]
        assert names == ["monitor_create", "monitor_list", "monitor_cancel"]

    def test_create_schema_requires_the_essentials(self):
        create = MonitorTool().get_actions_metadata()[0]
        params = create["parameters"]
        assert params["required"] == ["description", "source", "on_match"]
        assert params["properties"]["source"]["properties"]["type"]["enum"] == [
            "webpage", "tool", "ingest", "webhook", "approval"
        ]
        assert params["properties"]["check"]["properties"]["type"]["enum"] == [
            "changed", "new_items", "regex", "threshold", "status"
        ]

    def test_description_carries_the_policy(self):
        text = MonitorTool().get_actions_metadata()[0]["description"]
        for needle in ("only when the user asked", "scheduler", "only reads", "on_match", "Silence is not success"):
            assert needle in text


class TestActions:
    def test_needs_a_user(self):
        assert "signed-in" in json.loads(MonitorTool({}, None).execute_action(service.LIST))["error"]

    def test_routes_to_the_service_with_the_turns_executor(self, monkeypatch):
        seen = {}

        def create(caller, arguments):
            seen["caller"] = caller
            seen["arguments"] = arguments
            return {"monitor_id": "m1"}

        monkeypatch.setattr(service, "create", create)
        executor = executor_stub(conversation_id="c1", agent_id="a1")
        tool = MonitorTool({"executor": executor}, "u1")
        out = json.loads(tool.execute_action(service.CREATE, description="d"))
        assert out == {"monitor_id": "m1"}
        assert seen["caller"].conversation_id == "c1" and seen["caller"].agent_id == "a1"
        assert seen["caller"].executor is executor and seen["arguments"] == {"description": "d"}

    def test_cancel_is_scoped_to_the_conversation(self, monkeypatch):
        calls = []

        def end(monitor_id, user_id, status, reason=None, conversation_id=None):
            calls.append((monitor_id, user_id, status, conversation_id))
            return None

        monkeypatch.setattr(service, "end", end)
        tool = MonitorTool({"executor": executor_stub(conversation_id="c1")}, "u1")
        out = json.loads(tool.execute_action(service.CANCEL, monitor_id="m9"))
        assert "No active monitor" in out["error"]
        assert calls == [("m9", "u1", "cancelled", "c1")]

    def test_unknown_action(self):
        assert "Unknown action" in json.loads(MonitorTool({}, "u1").execute_action("delete"))["error"]


class TestApprovalHook:
    @pytest.fixture()
    def executor(self):
        executor = ToolExecutor(user="u1", decoded_token={"sub": "u1"})
        tools = {
            "monitor": {
                "id": "monitor",
                "name": "monitor",
                "actions": [{**a, "active": True} for a in MonitorTool().get_actions_metadata()],
            }
        }
        executor.prepare_tools_for_llm(tools)
        return executor, tools

    @pytest.mark.parametrize("needs", [True, False])
    def test_check_pause_asks_when_the_source_would(self, executor, monkeypatch, needs):
        tool_executor, tools = executor
        monkeypatch.setattr("docsgpt.monitors.service.create_needs_approval", lambda *a: needs)
        call = ToolCall(id="c1", name="monitor_create", arguments=json.dumps({"description": "d"}))
        pause = tool_executor.check_pause(tools, call, "OpenAILLM")
        if needs:
            assert pause["pause_type"] == "awaiting_approval" and pause["tool_name"] == "monitor"
        else:
            assert pause is None


class TestApprovedCallsAreRecorded:
    """The resume path records which calls the user approved, so ``monitor`` can bind only a real approval."""

    def _resume(self, decision):
        from tests.agents.test_continuation_tool_errors import _agent, _resume

        agent, _llm, _handler = _agent(Exception("boom"))
        agent.tool_executor.approved_call_ids = set()
        if decision == "denied":
            pending = [{"call_id": "c1", "name": "x", "llm_name": "x", "tool_name": "mcp_tool", "tool_id": "0",
                        "action_name": "x", "arguments": {}, "pause_type": "awaiting_approval"}]
            list(agent.gen_continuation([{"role": "system", "content": "s"}], {"0": {"name": "mcp_tool"}}, pending,
                                        [{"call_id": "c1", "decision": "denied"}]))
        else:
            _resume(agent)
        return agent.tool_executor.approved_call_ids

    def test_an_approved_call_is_recorded(self):
        assert self._resume("approved") == {"c1"}

    def test_a_denied_call_is_not(self):
        assert self._resume("denied") == set()
