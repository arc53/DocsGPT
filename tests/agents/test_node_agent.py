
import pytest


@pytest.mark.unit
class TestToolFilterMixin:

    def test_get_user_tools_filters_by_allowed_ids(self):
        from application.agents.workflows.node_agent import ToolFilterMixin

        class FakeBase:
            def _get_user_tools(self, user="local"):
                return {
                    "t1": {"_id": "id1", "name": "tool1"},
                    "t2": {"_id": "id2", "name": "tool2"},
                    "t3": {"_id": "id3", "name": "tool3"},
                }

        class TestClass(ToolFilterMixin, FakeBase):
            pass

        obj = TestClass()
        obj._allowed_tool_ids = ["id1", "id3"]
        result = obj._get_user_tools("user1")
        assert "t1" in result
        assert "t3" in result
        assert "t2" not in result

    def test_get_user_tools_returns_empty_when_no_allowed(self):
        from application.agents.workflows.node_agent import ToolFilterMixin

        class FakeBase:
            def _get_user_tools(self, user="local"):
                return {"t1": {"_id": "id1"}}

        class TestClass(ToolFilterMixin, FakeBase):
            pass

        obj = TestClass()
        obj._allowed_tool_ids = []
        result = obj._get_user_tools()
        assert result == {}

    def test_get_tools_filters_by_allowed_ids(self):
        from application.agents.workflows.node_agent import ToolFilterMixin

        class FakeBase:
            def _get_tools(self, api_key=None):
                return {
                    "t1": {"_id": "id1"},
                    "t2": {"_id": "id2"},
                }

        class TestClass(ToolFilterMixin, FakeBase):
            pass

        obj = TestClass()
        obj._allowed_tool_ids = ["id2"]
        result = obj._get_tools("key")
        assert "t2" in result
        assert "t1" not in result

    def test_get_tools_returns_empty_when_no_allowed(self):
        from application.agents.workflows.node_agent import ToolFilterMixin

        class FakeBase:
            def _get_tools(self, api_key=None):
                return {"t1": {"_id": "id1"}}

        class TestClass(ToolFilterMixin, FakeBase):
            pass

        obj = TestClass()
        obj._allowed_tool_ids = []
        result = obj._get_tools()
        assert result == {}


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


# =====================================================================
# Coverage gap tests  (lines 52-59: _WorkflowNodeMixin.__init__)
# =====================================================================


@pytest.mark.unit
class TestWorkflowNodeMixinInit:

    def test_mixin_init_sets_allowed_tool_ids(self):
        """Cover lines 52-59: _WorkflowNodeMixin.__init__ stores tool_ids."""
        from application.agents.workflows.node_agent import _WorkflowNodeMixin

        class FakeBase:
            def __init__(self, *args, **kwargs):
                pass

        class TestMixin(_WorkflowNodeMixin, FakeBase):
            pass

        obj = TestMixin(
            endpoint="http://example.com",
            llm_name="openai",
            model_id="gpt-4",
            api_key="key",
            tool_ids=["tool1", "tool2"],
        )
        assert obj._allowed_tool_ids == ["tool1", "tool2"]

    def test_mixin_init_defaults_empty_tool_ids(self):
        """Cover: _WorkflowNodeMixin defaults to empty list."""
        from application.agents.workflows.node_agent import _WorkflowNodeMixin

        class FakeBase:
            def __init__(self, *args, **kwargs):
                pass

        class TestMixin(_WorkflowNodeMixin, FakeBase):
            pass

        obj = TestMixin(
            endpoint="http://example.com",
            llm_name="openai",
            model_id="gpt-4",
            api_key="key",
        )
        assert obj._allowed_tool_ids == []
