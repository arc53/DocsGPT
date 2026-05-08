"""Tests for AgenticAgent — LLM-controlled retrieval agent."""

from unittest.mock import Mock

import pytest
from application.agents.agentic_agent import AgenticAgent


@pytest.fixture
def _no_tools(monkeypatch):
    monkeypatch.setattr(
        "application.agents.tool_executor.ToolExecutor.get_tools",
        lambda self: {},
    )


@pytest.mark.unit
class TestAgenticAgentInit:

    def test_initialization(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = AgenticAgent(**agent_base_params)
        assert isinstance(agent, AgenticAgent)
        assert agent.retriever_config == {}

    def test_initialization_with_retriever_config(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        rc = {"source": {"active_docs": ["abc"]}, "retriever_name": "classic"}
        agent = AgenticAgent(retriever_config=rc, **agent_base_params)
        assert agent.retriever_config == rc

    def test_inherits_base_properties(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = AgenticAgent(**agent_base_params)
        assert agent.endpoint == agent_base_params["endpoint"]
        assert agent.llm_name == agent_base_params["llm_name"]
        assert agent.model_id == agent_base_params["model_id"]


@pytest.mark.unit
class TestAgenticAgentGenInner:

    def test_basic_flow_yields_sources_and_tool_calls(
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

        agent = AgenticAgent(**agent_base_params)
        results = list(agent._gen_inner("Test query", log_context))

        sources = [r for r in results if "sources" in r]
        tool_calls = [r for r in results if "tool_calls" in r]
        assert len(sources) == 1
        assert len(tool_calls) == 1

    def test_logs_agent_component(
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
            yield "Done"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = AgenticAgent(**agent_base_params)
        list(agent._gen_inner("Query", log_context))

        agent_logs = [s for s in log_context.stacks if s["component"] == "agent"]
        assert len(agent_logs) == 1
        assert "tool_calls" in agent_logs[0]["data"]

    def test_no_pre_fetched_docs_in_messages(
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
            yield "Done"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = AgenticAgent(**agent_base_params)
        list(agent._gen_inner("Query", log_context))

        call_kwargs = mock_llm.gen_stream.call_args[1]
        messages = call_kwargs["messages"]
        # System prompt should not contain {summaries} replacement
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Query"


@pytest.mark.unit
class TestAgenticAgentCollectSources:

    def test_collect_internal_sources_from_cache(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = AgenticAgent(**agent_base_params)

        mock_tool = Mock()
        mock_tool.retrieved_docs = [
            {"text": "Found", "title": "Doc", "source": "test"},
        ]
        cache_key = f"internal_search:internal:{agent.user or ''}"
        agent.tool_executor._loaded_tools[cache_key] = mock_tool

        agent._collect_internal_sources()
        assert len(agent.retrieved_docs) == 1
        assert agent.retrieved_docs[0]["title"] == "Doc"

    def test_collect_internal_sources_no_cache(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        agent = AgenticAgent(**agent_base_params)
        agent._collect_internal_sources()
        assert agent.retrieved_docs == []
