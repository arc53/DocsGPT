"""Tests for ThinkTool — the chain-of-thought pseudo-tool."""

import pytest
from application.agents.tools.think import (
    THINK_TOOL_ENTRY,
    THINK_TOOL_ID,
    ThinkTool,
)


@pytest.mark.unit
class TestThinkTool:

    def test_id_constant(self):
        assert THINK_TOOL_ID == "think"

    def test_entry_has_reason_action(self):
        actions = THINK_TOOL_ENTRY["actions"]
        assert len(actions) == 1
        assert actions[0]["name"] == "reason"
        assert actions[0]["active"] is True

    def test_execute_reason_returns_continue(self):
        tool = ThinkTool()
        result = tool.execute_action("reason", reasoning="step by step thinking")
        assert result == "Continue."

    def test_execute_unknown_action_returns_continue(self):
        tool = ThinkTool()
        result = tool.execute_action("unknown_action")
        assert result == "Continue."

    def test_get_actions_metadata(self):
        tool = ThinkTool()
        meta = tool.get_actions_metadata()
        assert len(meta) == 1
        assert meta[0]["name"] == "reason"
        props = meta[0]["parameters"]["properties"]
        assert "reasoning" in props
        assert props["reasoning"]["filled_by_llm"] is True

    def test_get_config_requirements_empty(self):
        tool = ThinkTool()
        assert tool.get_config_requirements() == {}

    def test_init_accepts_no_config(self):
        tool = ThinkTool()
        assert tool is not None

    def test_init_accepts_config(self):
        tool = ThinkTool(config={"key": "value"})
        assert tool is not None
