from unittest.mock import Mock

import pytest
from application.agents.classic_agent import ClassicAgent
from application.agents.tools.internal_search import INTERNAL_TOOL_ID


@pytest.fixture
def _no_tools(monkeypatch):
    """Stub ToolExecutor.get_tools to avoid DB hits for most tests."""

    def _fake_get_tools(self):
        return {}

    monkeypatch.setattr(
        "application.agents.tool_executor.ToolExecutor.get_tools", _fake_get_tools
    )


@pytest.fixture
def _no_dir_structure(monkeypatch):
    """Stub the DB-backed directory-structure lookup used by the search tool."""
    monkeypatch.setattr(
        "application.agents.tools.internal_search.sources_have_directory_structure",
        lambda source: False,
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


@pytest.mark.unit
class TestClassicAgentSearchExposure:
    """ClassicAgent honors per-source exposure via an internal_search tool."""

    def test_default_registers_no_internal_search(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
        log_context,
    ):
        # No retriever_config (every source at default prefetch) → no search
        # tool is added and pre-fetched sources are preserved (unchanged).
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        agent = ClassicAgent(**agent_base_params)
        assert agent.retriever_config == {}

        captured = {}
        original_prepare = agent._prepare_tools

        def _spy(tools_dict):
            captured["tools_dict"] = tools_dict
            return original_prepare(tools_dict)

        agent._prepare_tools = _spy
        prefetched = [{"text": "pre", "title": "Pre", "source": "s"}]
        agent.retrieved_docs = list(prefetched)

        list(agent._gen_inner("q", log_context))

        assert INTERNAL_TOOL_ID not in captured["tools_dict"]
        # Pre-fetched sources untouched (no _collect_internal_sources overwrite).
        assert agent.retrieved_docs == prefetched

    def test_with_agentic_tool_source_registers_internal_search(
        self,
        agent_base_params,
        mock_llm,
        mock_llm_handler,
        mock_llm_creator,
        mock_llm_handler_creator,
        _no_tools,
        _no_dir_structure,
        log_context,
    ):
        # A retriever_config (agentic_tool subset) → the internal_search tool is
        # registered so the LLM can search that subset on demand.
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))

        def mock_handler(*args, **kwargs):
            yield "Processed"

        mock_llm_handler.process_message_flow = Mock(side_effect=mock_handler)

        retriever_config = {
            "source": {"active_docs": ["b"]},
            "retriever_name": "classic",
            "chunks": 2,
            "sources": [{"id": "b", "retrieval": None}],
        }
        agent = ClassicAgent(retriever_config=retriever_config, **agent_base_params)

        captured = {}
        original_prepare = agent._prepare_tools

        def _spy(tools_dict):
            captured["tools_dict"] = tools_dict
            return original_prepare(tools_dict)

        agent._prepare_tools = _spy

        list(agent._gen_inner("q", log_context))

        assert INTERNAL_TOOL_ID in captured["tools_dict"]
        assert captured["tools_dict"][INTERNAL_TOOL_ID]["name"] == "internal_search"

    def test_collect_internal_sources_surfaces_tool_docs(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        retriever_config = {"source": {"active_docs": ["b"]}}
        agent = ClassicAgent(retriever_config=retriever_config, **agent_base_params)

        mock_tool = Mock()
        mock_tool.retrieved_docs = [{"text": "Found", "title": "Doc", "source": "t"}]
        cache_key = f"internal_search:{INTERNAL_TOOL_ID}:{agent.user or ''}"
        agent.tool_executor._loaded_tools[cache_key] = mock_tool

        agent._collect_internal_sources()
        assert [d["title"] for d in agent.retrieved_docs] == ["Doc"]

    def test_collect_internal_sources_merges_with_prefetched(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        # Mixed exposure: a pre-fetched source's docs must survive alongside the
        # tool-retrieved docs (not be overwritten), so both are cited.
        retriever_config = {"source": {"active_docs": ["b"]}}
        agent = ClassicAgent(retriever_config=retriever_config, **agent_base_params)
        agent.retrieved_docs = [
            {"text": "Prefetched", "title": "Prefetched Doc", "source": "a"}
        ]
        mock_tool = Mock()
        mock_tool.retrieved_docs = [
            {"text": "Found", "title": "Tool Doc", "source": "b"}
        ]
        cache_key = f"internal_search:{INTERNAL_TOOL_ID}:{agent.user or ''}"
        agent.tool_executor._loaded_tools[cache_key] = mock_tool

        agent._collect_internal_sources()
        assert [d["title"] for d in agent.retrieved_docs] == [
            "Prefetched Doc",
            "Tool Doc",
        ]

    def test_collect_internal_sources_dedupes(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        retriever_config = {"source": {"active_docs": ["b"]}}
        agent = ClassicAgent(retriever_config=retriever_config, **agent_base_params)
        dup = {"text": "X", "title": "Dup", "source": "b"}
        agent.retrieved_docs = [dup]
        mock_tool = Mock()
        mock_tool.retrieved_docs = [dict(dup)]
        cache_key = f"internal_search:{INTERNAL_TOOL_ID}:{agent.user or ''}"
        agent.tool_executor._loaded_tools[cache_key] = mock_tool

        agent._collect_internal_sources()
        assert [d["title"] for d in agent.retrieved_docs] == ["Dup"]


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
