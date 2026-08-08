"""Tests for new agent types (agentic, research) in the workflow builder."""

from types import SimpleNamespace
from typing import Any, Dict

from unittest.mock import MagicMock

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
        # The node-source authorization gate is exercised separately;
        # these ids are fixtures with no rows to authorize against.
        monkeypatch.setattr(
            type(engine), "_authorized_node_sources",
            lambda self, sources: list(sources or []),
        )
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
        # The node-source authorization gate is exercised separately;
        # these ids are fixtures with no rows to authorize against.
        monkeypatch.setattr(
            type(engine), "_authorized_node_sources",
            lambda self, sources: list(sources or []),
        )
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


@pytest.mark.unit
class TestWorkflowNodeSourceAuthorization:
    """A node's ``sources`` are client-written and must be authorized.

    ``AgentNodeConfig.sources`` is stored verbatim from the workflow JSON and
    nothing validated it, so a node could name any tenant's source id and the
    retriever — which filters only on ``source_id`` — returned the documents.
    The check runs against the workflow *owner*, so a shared workflow keeps
    reading its owner's sources exactly like a shared agent does.
    """

    def _engine(self, owner):
        engine = create_engine()
        engine.agent._resolve_owner_id = lambda: owner
        return engine

    @staticmethod
    def _stub_db(monkeypatch):
        """``_authorized_node_sources`` opens a connection; don't need a real one."""
        import contextlib

        import application.storage.db.session as session

        @contextlib.contextmanager
        def _conn():
            yield MagicMock()

        monkeypatch.setattr(session, "db_readonly", _conn)

    def test_owner_sources_survive(self, monkeypatch):
        import application.api.user.team_sharing as ts

        self._stub_db(monkeypatch)
        monkeypatch.setattr(ts, "can_access", lambda *a, **k: True)
        engine = self._engine("owner")
        assert engine._authorized_node_sources(["s1", "s2"]) == ["s1", "s2"]

    def test_foreign_sources_are_dropped(self, monkeypatch):
        import application.api.user.team_sharing as ts

        self._stub_db(monkeypatch)
        monkeypatch.setattr(ts, "can_access", lambda conn, k, sid, u: sid == "mine")
        engine = self._engine("owner")
        assert engine._authorized_node_sources(["mine", "theirs"]) == ["mine"]

    def test_no_owner_drops_everything(self):
        engine = create_engine()
        engine.agent._resolve_owner_id = lambda: None
        engine.agent.decoded_token = {}
        engine.agent.user = None
        assert engine._authorized_node_sources(["s1"]) == []

    def test_authorization_error_fails_closed(self, monkeypatch):
        import application.api.user.team_sharing as ts

        def _boom(*a, **k):
            raise RuntimeError("db down")

        self._stub_db(monkeypatch)
        monkeypatch.setattr(ts, "can_access", _boom)
        engine = self._engine("owner")
        assert engine._authorized_node_sources(["s1"]) == []

    def test_empty_is_noop(self):
        assert create_engine()._authorized_node_sources([]) == []


@pytest.mark.unit
class TestWorkflowNodeDocumentsReachTheAgent:
    """A classic node's retrieved documents must reach its agent.

    Retrieval ran and the results were stashed on the *parent* agent for
    ``{{ source.* }}`` template resolution only, and ``factory_kwargs`` never
    carried them — so a node with a source and an ordinary prompt answered "I
    do not have any documents" while ``workflow_runs.status`` stayed
    ``completed``. Classic is the schema default, so this was the common case.
    """

    def test_retrieve_returns_the_documents(self, monkeypatch):
        engine = create_engine()
        docs = [{"text": "the radius is 88 metres", "title": "spec.md"}]

        class _R:
            def search(self, q):
                return docs

        monkeypatch.setattr(
            "application.retriever.retriever_creator.RetrieverCreator.create_retriever",
            lambda *a, **k: _R(),
        )
        monkeypatch.setattr(
            type(engine), "_authorized_node_sources", lambda self, s: list(s or [])
        )
        engine.state["query"] = "what is the radius?"
        cfg = create_agent_node(node_id="n", agent_type="classic", sources=["s1"])
        node_config = AgentNodeConfig(
            **cfg.config.get("config", cfg.config)
        )

        assert engine._retrieve_node_sources(node_config) == docs
        # still mirrored onto the parent for template resolution
        assert engine.agent.retrieved_docs == docs

    def test_retrieval_failure_returns_empty_not_none(self, monkeypatch):
        engine = create_engine()

        def _boom(*a, **k):
            raise RuntimeError("vector store down")

        monkeypatch.setattr(
            "application.retriever.retriever_creator.RetrieverCreator.create_retriever",
            _boom,
        )
        monkeypatch.setattr(
            type(engine), "_authorized_node_sources", lambda self, s: list(s or [])
        )
        engine.state["query"] = "q"
        cfg = create_agent_node(node_id="n", agent_type="classic", sources=["s1"])
        node_config = AgentNodeConfig(**cfg.config.get("config", cfg.config))

        assert engine._retrieve_node_sources(node_config) == []
