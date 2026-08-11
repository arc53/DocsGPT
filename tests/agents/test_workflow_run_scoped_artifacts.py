"""Regression tests: workflow AGENT nodes run-scope their artifact tools.

The engine stamps each node agent's ``ToolExecutor.workflow_run_id`` so run-aware
tools (artifact_generator / code_executor) address artifacts by the workflow run.
``ToolExecutor._get_or_load_tool`` then stamps ``workflow_run_id`` into the loaded
tool's ``tool_config`` only when set, so a short ref (A1) created by one node
resolves for ``edit_artifact`` in a later node within the same run.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import Mock

import pytest

from application.agents.tool_executor import ToolExecutor
from application.agents.workflows.node_agent import WorkflowNodeAgentFactory
from application.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowGraph,
    WorkflowNode,
)
from application.agents.workflows.workflow_engine import WorkflowEngine


class _StubNodeAgent:
    """Node-agent stub carrying a real ToolExecutor and an LLM-free gen()."""

    def __init__(self, events: list) -> None:
        self.events = events
        self.tool_executor = ToolExecutor(user="user-1")

    def gen(self, _prompt: str):
        yield from self.events


def _create_engine(workflow_run_id: Optional[str] = None) -> WorkflowEngine:
    """Build an engine bound to a bare agent stub (no LLM)."""
    graph = WorkflowGraph(workflow=Workflow(name="Run Scope Test"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="test-key",
        chat_history=[],
        decoded_token={"sub": "user-1"},
    )
    return WorkflowEngine(graph, agent, workflow_run_id=workflow_run_id)


def _agent_node(node_id: str = "agent_1") -> WorkflowNode:
    """Minimal classic AGENT node config."""
    return WorkflowNode(
        id=node_id,
        workflow_id="workflow-1",
        type=NodeType.AGENT,
        title="Agent",
        position={"x": 0, "y": 0},
        config={
            "agent_type": "classic",
            "system_prompt": "You are a helpful assistant.",
            "prompt_template": "",
            "stream_to_user": False,
            "tools": [],
        },
    )


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------


def test_agent_node_run_scopes_tool_executor(monkeypatch):
    """The node agent's ToolExecutor inherits the engine's workflow_run_id."""
    engine = _create_engine(workflow_run_id="22222222-2222-2222-2222-222222222222")
    node = _agent_node()
    stub = _StubNodeAgent([{"answer": "done"}])

    monkeypatch.setattr(
        WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: stub)
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider", lambda _provider: None
    )

    list(engine._execute_agent_node(node))

    assert stub.tool_executor.workflow_run_id == engine.workflow_run_id
    # Both-parents safety: a workflow node addresses artifacts by run, never by a
    # conversation. If a conversation_id ever leaks into the node agent, the
    # run-scoped parent gate would have two parents — fail here instead.
    assert stub.tool_executor.conversation_id is None


def test_agent_node_skips_run_scope_when_not_persisted(monkeypatch):
    """An unpersisted run must NOT stamp workflow_run_id (it would orphan artifacts)."""
    engine = _create_engine(workflow_run_id="22222222-2222-2222-2222-222222222222")
    engine.run_persisted = False
    node = _agent_node()
    stub = _StubNodeAgent([{"answer": "done"}])

    monkeypatch.setattr(
        WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: stub)
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider", lambda _provider: None
    )

    list(engine._execute_agent_node(node))

    # Left unset: the run-scoped tools then persist under a conversation parent or
    # cleanly error, never orphaning an artifact under a nonexistent run row.
    assert stub.tool_executor.workflow_run_id is None


# ---------------------------------------------------------------------------
# ToolExecutor stamping
# ---------------------------------------------------------------------------


def _capture_tool_config(monkeypatch) -> Dict[str, Any]:
    """Patch ToolManager so _get_or_load_tool's tool_config is captured."""
    captured: Dict[str, Any] = {}
    mock_tm = Mock()
    mock_tm.load_tool.return_value = Mock()

    def _load_tool(name, tool_config, user_id=None):
        captured["tool_config"] = tool_config
        return mock_tm.load_tool.return_value

    mock_tm.load_tool.side_effect = _load_tool
    monkeypatch.setattr(
        "application.agents.tool_executor.ToolManager", lambda config: mock_tm
    )
    return captured


def test_get_or_load_tool_stamps_workflow_run_id_when_set(monkeypatch):
    """A run-scoped executor stamps workflow_run_id into a tool's tool_config."""
    captured = _capture_tool_config(monkeypatch)
    executor = ToolExecutor(user="user-1")
    executor.workflow_run_id = "33333333-3333-3333-3333-333333333333"
    tool_data = {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "name": "artifact_generator",
        "config": {},
    }

    executor._get_or_load_tool(tool_data, "t1", "create_artifact")

    assert captured["tool_config"]["workflow_run_id"] == executor.workflow_run_id
    # A run-scoped node has no conversation parent.
    assert "conversation_id" not in captured["tool_config"]


def test_get_or_load_tool_omits_workflow_run_id_for_chat(monkeypatch):
    """The chat case (no workflow_run_id) leaves it off the tool_config."""
    captured = _capture_tool_config(monkeypatch)
    executor = ToolExecutor(user="user-1")
    executor.conversation_id = "conv-1"
    tool_data = {
        "id": "00000000-0000-0000-0000-0000000000bb",
        "name": "artifact_generator",
        "config": {},
    }

    executor._get_or_load_tool(tool_data, "t2", "create_artifact")

    assert "workflow_run_id" not in captured["tool_config"]
    assert captured["tool_config"]["conversation_id"] == "conv-1"


# ---------------------------------------------------------------------------
# Run-scoped resolution against real Postgres + storage (no LLM, no sandbox)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_scoped_ref_resolves_for_edit(pg_engine, tmp_path, monkeypatch):
    """A1 created under a workflow_run_id resolves for edit_artifact -> v2."""
    pytest.importorskip("jsonschema")
    from application.agents.tools.artifact_generator import ArtifactGeneratorTool
    from application.storage.db.repositories.artifacts import ArtifactsRepository
    from application.storage.local import LocalStorage
    from application.storage.storage_creator import StorageCreator

    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(StorageCreator, "_instance", storage, raising=False)
    monkeypatch.setattr(
        "application.storage.db.session.get_engine", lambda: pg_engine
    )
    # Skip the Jupyter-gateway renderer: the run-scoping under test is the ref
    # resolution + version append, not the rendered bytes.
    monkeypatch.setattr(
        ArtifactGeneratorTool, "_render", lambda self, kind, spec: {"data": b"%PDF-1.4 stub"}
    )

    workflow_run_id = str(uuid.uuid4())
    tool = ArtifactGeneratorTool(
        tool_config={"workflow_run_id": workflow_run_id, "tool_id": str(uuid.uuid4())},
        user_id="user-run",
    )

    created = tool.execute_action(
        "create_artifact", kind="presentation", title="Deck", spec={"slides": [{"title": "a"}]}
    )
    assert created["status"] == "ok", created
    assert created["version"] == 1
    assert created["ref"] == "A1"
    artifact_id = created["artifact_id"]

    # edit_artifact by the run-scoped short ref resolves the same artifact -> v2.
    edited = tool.execute_action(
        "edit_artifact", id="A1", spec_patch={"slides": [{"title": "a"}, {"title": "b"}]}
    )
    assert edited["status"] == "ok", edited
    assert edited["version"] == 2
    assert edited["artifact_id"] == artifact_id

    with pg_engine.connect() as conn:
        repo = ArtifactsRepository(conn)
        artifact = repo.get_artifact_in_parent(artifact_id, workflow_run_id=workflow_run_id)
        v2 = repo.get_version(artifact_id, 2)
    assert artifact["current_version"] == 2
    assert len(v2["spec"]["slides"]) == 2
