"""A duplicate builtin registration must not drop the row that carries the gate.

``code_executor`` can arrive twice — the user's stored ``user_tools`` row and the
synthesized default — and the picker labels both "Code Executor". Collapsing them
by insertion order meant the agent's click order decided which survived, and the
survivor is the only row consulted for approval, so a gated row landing second
was silently dropped and ``run_code`` ran unapproved.
"""

from __future__ import annotations

import pytest

from application.agents.default_tools import default_tool_id
from application.agents.tool_executor import ToolExecutor

SYNTHESIZED_ID = default_tool_id("code_executor")
STORED_ID = "9f1d4c2e-0000-4000-8000-000000000001"


def _row(*, action_approval=False, config_approval=False):
    return {
        "name": "code_executor",
        "actions": [
            {"name": "run_code", "active": True, "require_approval": action_approval}
        ],
        "config": {"require_approval": True} if config_approval else {},
    }


def _survivor(tools_dict):
    executor = ToolExecutor()
    schemas = executor.prepare_tools_for_llm(tools_dict)
    assert len(schemas) == 1, schemas
    tool_id, _action = executor._name_to_tool["run_code"]
    return tool_id


@pytest.mark.unit
class TestDuplicateBuiltinRegistration:
    def test_gated_action_snapshot_survives_when_listed_second(self):
        tools = {
            SYNTHESIZED_ID: _row(),
            STORED_ID: _row(action_approval=True),
        }
        assert _survivor(tools) == STORED_ID

    def test_gated_deployment_config_survives_when_listed_second(self):
        tools = {
            SYNTHESIZED_ID: _row(),
            STORED_ID: _row(config_approval=True),
        }
        assert _survivor(tools) == STORED_ID

    def test_stored_row_wins_over_the_synthesized_copy(self):
        """Neither carries a gate: the stored row is still the one with config."""
        tools = {
            SYNTHESIZED_ID: _row(),
            STORED_ID: _row(),
        }
        assert _survivor(tools) == STORED_ID

    def test_gate_survives_between_two_stored_rows(self):
        other = "9f1d4c2e-0000-4000-8000-000000000002"
        tools = {
            STORED_ID: _row(),
            other: _row(action_approval=True),
        }
        assert _survivor(tools) == other

    def test_still_collapses_to_a_single_callable_name(self):
        tools = {
            SYNTHESIZED_ID: _row(),
            STORED_ID: _row(action_approval=True),
        }
        executor = ToolExecutor()
        schemas = executor.prepare_tools_for_llm(tools)
        names = [s["function"]["name"] for s in schemas]
        assert names == ["run_code"], names
