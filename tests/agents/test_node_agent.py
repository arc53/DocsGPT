
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def _no_db(monkeypatch):
    """Scoped-id resolution opens a read conn; synthetic ids never use it."""

    @contextmanager
    def fake_readonly():
        yield MagicMock()

    monkeypatch.setattr("application.agents.tool_executor.db_readonly", fake_readonly)


class _FakeExecutorBase:
    """Stands in for BaseAgent: provides the tool_executor the mixin scopes."""

    def __init__(self, *args, **kwargs):
        from application.agents.tool_executor import ToolExecutor

        self.tool_executor = ToolExecutor()


@pytest.mark.unit
class TestWorkflowNodeAgentFactory:

    def test_raises_on_unsupported_type(self):
        from application.agents.workflows.node_agent import WorkflowNodeAgentFactory

        with pytest.raises(ValueError, match="Unsupported agent type"):
            WorkflowNodeAgentFactory.create(
                agent_type="nonexistent",
                endpoint="http://example.com",
                llm_name="openai",
                model_id="gpt-4",
                api_key="key",
            )


@pytest.mark.unit
class TestWorkflowNodeMixinInit:
    """The mixin scopes the EXECUTOR: agents fetch tools via tool_executor.get_tools(),
    so per-node tool filtering must live there (the old agent-method mixin was dead code)."""

    def _mixed(self, **kwargs):
        from application.agents.workflows.node_agent import _WorkflowNodeMixin

        class TestMixin(_WorkflowNodeMixin, _FakeExecutorBase):
            pass

        return TestMixin(
            endpoint="http://example.com",
            llm_name="openai",
            model_id="gpt-4",
            api_key="key",
            **kwargs,
        )

    def test_mixin_scopes_executor_to_tool_ids(self):
        obj = self._mixed(tool_ids=["tool1", "tool2"])
        assert obj.tool_executor.allowed_tool_ids == ["tool1", "tool2"]

    def test_mixin_defaults_to_empty_scope_not_unscoped(self):
        # No tool_ids means the node gets NO tools — never the user's full set.
        obj = self._mixed()
        assert obj.tool_executor.allowed_tool_ids == []

    def test_empty_scope_yields_no_tools(self):
        obj = self._mixed()
        assert obj.tool_executor.get_tools() == {}

    def test_scoped_executor_resolves_builtin_synthetic_ids(self, _no_db):
        """A node whose Tools picker selected a builtin (Artifact / Read Document)
        must get that tool at runtime — the P0 this design replaced."""
        from application.agents.default_tools import default_tool_id

        obj = self._mixed(
            tool_ids=[
                default_tool_id("artifact_generator"),
                default_tool_id("read_document"),
            ]
        )
        tools = obj.tool_executor.get_tools()
        names = {t["name"] for t in tools.values()}
        assert names == {"artifact_generator", "read_document"}

    def test_scoped_executor_drops_unresolvable_ids(self, _no_db):
        obj = self._mixed(tool_ids=["not-a-real-tool-id"])
        assert obj.tool_executor.get_tools() == {}
