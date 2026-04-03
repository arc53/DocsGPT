"""Tests for new agent types (agentic, research) in the workflow builder."""

from types import SimpleNamespace
from typing import Any, Dict

import pytest

from application.agents.agentic_agent import AgenticAgent
from application.agents.classic_agent import ClassicAgent
from application.agents.research_agent import ResearchAgent
from application.agents.workflows.node_agent import (
    WorkflowNodeAgenticAgent,
    WorkflowNodeAgentFactory,
    WorkflowNodeClassicAgent,
    WorkflowNodeResearchAgent,
)
from application.agents.workflows.schemas import (
    AgentNodeConfig,
    AgentType,
    NodeType,
    Workflow,
    WorkflowGraph,
    WorkflowNode,
)
from application.agents.workflows.workflow_engine import WorkflowEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubNodeAgent:
    """Minimal agent stub that yields pre-defined events."""

    def __init__(self, events):
        self.events = events

    def gen(self, _prompt):
        yield from self.events


def create_engine() -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Test"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="test-key",
        chat_history=[],
        decoded_token={"sub": "user-1"},
    )
    return WorkflowEngine(graph, agent)


def create_agent_node(
    node_id: str,
    agent_type: str = "classic",
    sources: list = None,
    chunks: str = "2",
    retriever: str = "",
    output_variable: str = "",
) -> WorkflowNode:
    config: Dict[str, Any] = {
        "agent_type": agent_type,
        "system_prompt": "You are a helpful assistant.",
        "prompt_template": "",
        "stream_to_user": False,
        "tools": [],
        "sources": sources or [],
        "chunks": chunks,
        "retriever": retriever,
    }
    if output_variable:
        config["output_variable"] = output_variable
    return WorkflowNode(
        id=node_id,
        workflow_id="workflow-1",
        type=NodeType.AGENT,
        title="Agent",
        position={"x": 0, "y": 0},
        config=config,
    )


# ---------------------------------------------------------------------------
# AgentType enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentTypeEnum:

    def test_agentic_value_exists(self):
        assert AgentType.AGENTIC == "agentic"

    def test_research_value_exists(self):
        assert AgentType.RESEARCH == "research"

    def test_classic_still_exists(self):
        assert AgentType.CLASSIC == "classic"

    def test_react_still_exists(self):
        assert AgentType.REACT == "react"


# ---------------------------------------------------------------------------
# AgentNodeConfig schema validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentNodeConfigValidation:

    def test_accepts_agentic_agent_type(self):
        config = AgentNodeConfig(agent_type="agentic")
        assert config.agent_type == AgentType.AGENTIC

    def test_accepts_research_agent_type(self):
        config = AgentNodeConfig(agent_type="research")
        assert config.agent_type == AgentType.RESEARCH

    def test_rejects_unknown_agent_type(self):
        with pytest.raises(Exception):
            AgentNodeConfig(agent_type="nonexistent")

    def test_default_agent_type_is_classic(self):
        config = AgentNodeConfig()
        assert config.agent_type == AgentType.CLASSIC


# ---------------------------------------------------------------------------
# WorkflowNodeAgentFactory registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowNodeAgentFactoryRegistry:

    def test_factory_has_agentic(self):
        assert AgentType.AGENTIC in WorkflowNodeAgentFactory._agents
        assert WorkflowNodeAgentFactory._agents[AgentType.AGENTIC] is WorkflowNodeAgenticAgent

    def test_factory_has_research(self):
        assert AgentType.RESEARCH in WorkflowNodeAgentFactory._agents
        assert WorkflowNodeAgentFactory._agents[AgentType.RESEARCH] is WorkflowNodeResearchAgent

    def test_factory_raises_for_unknown_type(self):
        with pytest.raises(ValueError, match="Unsupported agent type"):
            WorkflowNodeAgentFactory.create(
                agent_type="nonexistent",
                endpoint="stream",
                llm_name="openai",
                model_id="gpt-4o-mini",
                api_key="key",
            )


# ---------------------------------------------------------------------------
# WorkflowNode agent classes (inheritance)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkflowNodeAgentClasses:

    def test_agentic_agent_inherits_correctly(self):
        assert issubclass(WorkflowNodeAgenticAgent, AgenticAgent)

    def test_research_agent_inherits_correctly(self):
        assert issubclass(WorkflowNodeResearchAgent, ResearchAgent)

    def test_classic_agent_inherits_correctly(self):
        assert issubclass(WorkflowNodeClassicAgent, ClassicAgent)


# ---------------------------------------------------------------------------
# Workflow engine: agentic agent node execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowEngineAgenticNode:

    def test_agentic_node_executes_and_saves_output(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(
            node_id="agent_agentic",
            agent_type="agentic",
            output_variable="result",
        )
        node_events = [{"answer": "agentic answer"}]

        captured: Dict[str, Any] = {}

        def capture_create(**kwargs):
            captured.update(kwargs)
            return StubNodeAgent(node_events)

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(capture_create),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        list(engine._execute_agent_node(node))

        assert engine.state["node_agent_agentic_output"] == "agentic answer"
        assert engine.state["result"] == "agentic answer"

    def test_agentic_node_passes_retriever_config(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(
            node_id="agent_rc",
            agent_type="agentic",
            sources=["source-abc"],
            chunks="4",
            retriever="semantic",
        )
        node_events = [{"answer": "ok"}]

        captured: Dict[str, Any] = {}

        def capture_create(**kwargs):
            captured.update(kwargs)
            return StubNodeAgent(node_events)

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(capture_create),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        list(engine._execute_agent_node(node))

        rc = captured.get("retriever_config")
        assert rc is not None
        assert rc["source"] == {"active_docs": ["source-abc"]}
        assert rc["retriever_name"] == "semantic"
        assert rc["chunks"] == 4

    def test_agentic_node_empty_sources_gives_empty_source_dict(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(
            node_id="agent_nosrc",
            agent_type="agentic",
            sources=[],
        )
        node_events = [{"answer": "ok"}]

        captured: Dict[str, Any] = {}

        def capture_create(**kwargs):
            captured.update(kwargs)
            return StubNodeAgent(node_events)

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(capture_create),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        list(engine._execute_agent_node(node))

        rc = captured["retriever_config"]
        assert rc["source"] == {}


# ---------------------------------------------------------------------------
# Workflow engine: research agent node execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowEngineResearchNode:

    def test_research_node_executes_and_saves_output(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(
            node_id="agent_research",
            agent_type="research",
            output_variable="report",
        )
        node_events = [{"answer": "research report"}]

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        list(engine._execute_agent_node(node))

        assert engine.state["node_agent_research_output"] == "research report"
        assert engine.state["report"] == "research report"

    def test_research_node_passes_retriever_config(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(
            node_id="agent_rr",
            agent_type="research",
            sources=["doc-1", "doc-2"],
            chunks="6",
        )
        node_events = [{"answer": "ok"}]

        captured: Dict[str, Any] = {}

        def capture_create(**kwargs):
            captured.update(kwargs)
            return StubNodeAgent(node_events)

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(capture_create),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        list(engine._execute_agent_node(node))

        rc = captured["retriever_config"]
        assert rc["source"] == {"active_docs": ["doc-1", "doc-2"]}
        assert rc["chunks"] == 6
        assert rc["decoded_token"] == {"sub": "user-1"}

    def test_research_node_handles_structured_output(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(
            node_id="agent_rs",
            agent_type="research",
            output_variable="data",
        )
        # Simulate structured JSON output from research agent
        node_events = [
            {"answer": '{"findings": "important"}', "structured": True},
        ]

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        list(engine._execute_agent_node(node))

        # structured=True causes the engine to parse JSON
        assert engine.state["data"] == {"findings": "important"}


# ---------------------------------------------------------------------------
# Workflow engine: classic node does NOT get retriever_config
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowEngineClassicNodeNoRetrieverConfig:

    def test_classic_node_does_not_pass_retriever_config(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(
            node_id="agent_classic",
            agent_type="classic",
            sources=["some-source"],
        )
        node_events = [{"answer": "classic answer"}]

        captured: Dict[str, Any] = {}

        def capture_create(**kwargs):
            captured.update(kwargs)
            return StubNodeAgent(node_events)

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(capture_create),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        list(engine._execute_agent_node(node))

        assert "retriever_config" not in captured


# ---------------------------------------------------------------------------
# Workflow engine: streaming events from new agent types
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowEngineStreamingEvents:

    def test_agentic_node_streams_answer_events(self, monkeypatch):
        engine = create_engine()
        node = create_agent_node(node_id="agent_s1", agent_type="agentic")
        # Modify config to enable streaming
        node.config["stream_to_user"] = True

        node_events = [
            {"answer": "chunk 1"},
            {"answer": "chunk 2"},
        ]

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        results = list(engine._execute_agent_node(node))
        answer_events = [r for r in results if "answer" in r]
        assert len(answer_events) == 2

    def test_research_node_passes_through_non_answer_events(self, monkeypatch):
        """Research agents yield research_plan/research_progress events.
        The workflow engine only forwards 'answer' events to the user."""
        engine = create_engine()
        node = create_agent_node(node_id="agent_s2", agent_type="research")
        node.config["stream_to_user"] = True

        node_events = [
            {"type": "research_plan", "data": {"steps": [], "complexity": "simple"}},
            {"type": "research_progress", "data": {"status": "planning"}},
            {"answer": "final report"},
        ]

        monkeypatch.setattr(
            WorkflowNodeAgentFactory,
            "create",
            staticmethod(lambda **kwargs: StubNodeAgent(node_events)),
        )
        monkeypatch.setattr(
            "application.core.model_utils.get_api_key_for_provider",
            lambda _provider: None,
        )

        results = list(engine._execute_agent_node(node))
        # Only answer events are streamed to user
        answer_events = [r for r in results if "answer" in r]
        assert len(answer_events) == 1
        assert answer_events[0]["answer"] == "final report"

        # State still captures the full text
        assert engine.state["node_agent_s2_output"] == "final report"
