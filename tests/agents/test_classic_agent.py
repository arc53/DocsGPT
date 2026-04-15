from unittest.mock import Mock

import pytest
from application.agents.classic_agent import ClassicAgent


@pytest.fixture
def _no_tools(monkeypatch):
    """Stub ToolExecutor.get_tools to avoid DB hits for most tests."""

    def _fake_get_tools(self):
        return {}

    monkeypatch.setattr(
        "application.agents.tool_executor.ToolExecutor.get_tools", _fake_get_tools
    )


@pytest.mark.unit
class TestClassicAgent:

    def test_classic_agent_initialization(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = ClassicAgent(**agent_base_params)

        assert isinstance(agent, ClassicAgent)
        assert agent.endpoint == agent_base_params["endpoint"]
        assert agent.llm_name == agent_base_params["llm_name"]

    def test_gen_inner_basic_flow(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
        log_context,
    ):
        def mock_gen_stream(*args, **kwargs):
            yield "Answer chunk 1"
            yield "Answer chunk 2"

        mock_llm.gen_stream = Mock(return_value=mock_gen_stream())

        def mock_handler(*args, **kwargs):
            yield "Processed answer"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)

        results = list(agent._gen_inner("Test query", log_context))

        assert len(results) >= 2
        sources = [r for r in results if "sources" in r]
        tool_calls = [r for r in results if "tool_calls" in r]

        assert len(sources) == 1
        assert len(tool_calls) == 1

    def test_gen_inner_retrieves_documents(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)
        list(agent._gen_inner("Test query", log_context))

    def test_gen_inner_uses_user_tools(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        monkeypatch,
        log_context,
    ):
        # Inject a fake user tool dict via get_tools rather than touching DB.
        fake_tools = {
            "t1": {
                "id": "t1",
                "name": "test_tool",
                "config": {},
                "actions": [
                    {
                        "name": "do_thing",
                        "description": "",
                        "active": True,
                        "parameters": {"properties": {}},
                    }
                ],
            }
        }
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolExecutor.get_tools",
            lambda self: fake_tools,
        )

        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)
        list(agent._gen_inner("Test query", log_context))

        # After _prepare_tools, the fake user tool should have become an llm tool schema.
        assert any(
            t["function"]["name"] == "do_thing" for t in agent.tools
        )

    def test_gen_inner_builds_correct_messages(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)
        list(agent._gen_inner("Test query", log_context))

        call_kwargs = mock_llm.gen_stream.call_args[1]
        messages = call_kwargs["messages"]

        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Test query"

    def test_gen_inner_logs_tool_calls(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
        log_context,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)
        agent.tool_calls = [{"tool": "test", "result": "success"}]

        list(agent._gen_inner("Test query", log_context))

        agent_logs = [s for s in log_context.stacks if s["component"] == "agent"]
        assert len(agent_logs) == 1
        assert "tool_calls" in agent_logs[0]["data"]


@pytest.mark.integration
class TestClassicAgentIntegration:

    def test_gen_method_with_logging(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)

        results = list(agent.gen("Test query"))

        assert len(results) >= 1

    def test_gen_method_decorator_applied(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
    ):
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)

        assert hasattr(agent.gen, "__wrapped__")
