"""A node's custom model resolves in the account of whoever chose it.

A model set on a node was picked by the workflow's author, so it resolves in
the workflow owner's account whoever runs the workflow: a shared or published
workflow agent must not look the owner's custom model up in the caller's
account. A node without a model runs on the run's model, in the run's scope
(the parent agent's ``model_user_id``, else the caller), as before.

These run the real model registry, provider resolution, node agent factory
and ``LLMCreator``; only the per-user model layer and the node's reply are
stubbed.
"""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace
from typing import Dict, Optional

import pytest

from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory
from docsgpt.agents.workflows.schemas import NodeType, Workflow, WorkflowGraph, WorkflowNode
from docsgpt.agents.workflows.workflow_engine import WorkflowEngine
from docsgpt.core.model_registry import ModelRegistry
from docsgpt.core.model_settings import AvailableModel, ModelCapabilities, ModelProvider
from docsgpt.core.model_yaml import BUILTIN_MODELS_DIR, load_model_yamls
from docsgpt.core.settings import settings
from docsgpt.llm.llm_creator import ModelNotAvailableError

OWNER = "owner-1"
CALLER = "caller-1"

_LLM_SETTINGS = (
    "LLM_PROVIDER",
    "LLM_NAME",
    "API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MODELS_CONFIG_DIR",
    "FALLBACK_LLM_PROVIDER",
    "FALLBACK_LLM_NAME",
    "FALLBACK_LLM_API_KEY",
)


def _custom_model(key: str, *, structured: bool = True) -> AvailableModel:
    """A user's own OpenAI-compatible model with its own key and endpoint."""
    return AvailableModel(
        id=str(uuid.uuid4()),
        provider=ModelProvider.OPENAI_COMPATIBLE,
        display_name="Mine",
        capabilities=ModelCapabilities(supports_tools=True, supports_structured_output=structured),
        base_url="https://api.example.com/v1",
        upstream_model_id="my-model",
        source="user",
        api_key=key,
    )


@pytest.fixture
def user_models(monkeypatch) -> Dict[str, Dict[str, AvailableModel]]:
    """Each user's custom models, by user id; fill it in the test."""
    import docsgpt.security.safe_url as safe_url

    for name in _LLM_SETTINGS:
        monkeypatch.setattr(settings, name, None)
    for catalog in load_model_yamls([BUILTIN_MODELS_DIR]):
        if catalog.api_key_env:
            monkeypatch.delenv(catalog.api_key_env, raising=False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "API_KEY", "sk-deployment")
    ModelRegistry.reset()
    layers: Dict[str, Dict[str, AvailableModel]] = {}
    monkeypatch.setattr(
        ModelRegistry, "_user_models_for", lambda self, user_id: dict(layers.get(user_id, {}))
    )
    monkeypatch.setattr(safe_url, "validate_user_base_url", lambda url: None)
    monkeypatch.setattr(safe_url, "pinned_httpx_client", lambda url: None)
    yield layers
    ModelRegistry.reset()


@pytest.fixture
def built_agents(monkeypatch):
    """Build each node agent for real (its LLM included), then answer ``ok``."""
    real_create = WorkflowNodeAgentFactory.create.__func__
    agents = []

    class _Reply:
        def __init__(self, agent):
            self.llm = agent.llm
            self.tool_executor = None

        def gen(self, _prompt):
            yield {"answer": "ok"}

    def _create(**kwargs):
        agent = real_create(WorkflowNodeAgentFactory, **kwargs)
        agents.append(agent)
        return _Reply(agent)

    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(_create))
    return agents


def _engine(*, parent_model_id: str = "gpt-4o-mini", parent_model_user_id: Optional[str] = None) -> WorkflowEngine:
    """A shared workflow agent of ``OWNER``, run by ``CALLER``."""
    graph = WorkflowGraph(workflow=Workflow(name="Shared"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id=parent_model_id,
        model_user_id=parent_model_user_id,
        api_key=None,
        chat_history=[],
        decoded_token={"sub": CALLER},
        user=CALLER,
        workflow_owner=OWNER,
        _resolve_owner_id=lambda: OWNER,
    )
    engine = WorkflowEngine(graph, agent)
    engine.state["query"] = "hi"
    return engine


def _node(model_id: Optional[str] = None, *, json_schema: Optional[dict] = None) -> WorkflowNode:
    config = {
        "agent_type": "classic",
        "system_prompt": "You help.",
        "prompt_template": "",
        "stream_to_user": False,
        "tools": [],
    }
    if model_id:
        config["model_id"] = model_id
        config["llm_name"] = "openai_compatible"
    if json_schema is not None:
        config["json_schema"] = json_schema
    return WorkflowNode(
        id="agent-1",
        workflow_id="workflow-1",
        type=NodeType.AGENT,
        title="Agent",
        position={"x": 0, "y": 0},
        config=config,
    )


def test_a_node_pinned_to_the_owners_custom_model_runs_for_another_user(user_models, built_agents):
    owners = _custom_model("sk-owners-own")
    user_models[OWNER] = {owners.id: owners}
    engine = _engine()

    list(engine._execute_agent_node(_node(owners.id)))

    llm = built_agents[0].llm
    assert built_agents[0].model_user_id == OWNER
    assert llm.model_user_id == OWNER
    assert (llm.api_key, llm._effective_base_url) == ("sk-owners-own", "https://api.example.com/v1")
    assert llm.model_id == "my-model"
    assert engine.state[f"node_{'agent-1'}_output"] == "ok"


def test_a_loop_bodys_node_resolves_the_owners_model_too(user_models, built_agents):
    owners = _custom_model("sk-owners-own")
    user_models[OWNER] = {owners.id: owners}
    child = _engine()._loop_child(_node(), 0, 1, threading.Event())

    list(child._execute_agent_node(_node(owners.id)))

    assert built_agents[0].llm.model_user_id == OWNER


def test_an_agentic_nodes_search_resolves_the_owners_model(user_models, built_agents, monkeypatch):
    owners = _custom_model("sk-owners-own")
    user_models[OWNER] = {owners.id: owners}
    engine = _engine()
    monkeypatch.setattr(engine, "_retrieve_node_sources", lambda _config: [])
    monkeypatch.setattr(engine, "_authorized_node_sources", lambda sources: ",".join(sources))
    node = _node(owners.id)
    node.config.update(agent_type="agentic", sources=["src-1"])

    list(engine._execute_agent_node(node))

    assert built_agents[0].retriever_config["model_user_id"] == OWNER


def test_a_pinned_model_the_owner_no_longer_has_still_fails(user_models, built_agents):
    # Even when the caller happens to hold a model under that id, the owner's
    # node never falls through to the caller's account.
    gone = _custom_model("sk-callers-own")
    user_models[CALLER] = {gone.id: gone}
    engine = _engine()

    with pytest.raises(ModelNotAvailableError):
        list(engine._execute_agent_node(_node(gone.id)))


def test_a_node_without_a_model_still_runs_in_the_callers_scope(user_models, built_agents):
    callers = _custom_model("sk-callers-own")
    user_models[CALLER] = {callers.id: callers}
    engine = _engine(parent_model_id=callers.id)

    list(engine._execute_agent_node(_node()))

    llm = built_agents[0].llm
    assert built_agents[0].model_user_id is None
    assert llm.model_user_id == CALLER
    assert llm.api_key == "sk-callers-own"


def test_a_node_without_a_model_keeps_the_parent_agents_scope(user_models, built_agents):
    owners = _custom_model("sk-owners-own")
    user_models[OWNER] = {owners.id: owners}
    engine = _engine(parent_model_id=owners.id, parent_model_user_id=OWNER)

    list(engine._execute_agent_node(_node()))

    assert built_agents[0].llm.model_user_id == OWNER
    assert built_agents[0].llm.api_key == "sk-owners-own"


def test_the_structured_output_check_reads_the_owners_model(user_models, built_agents):
    owners = _custom_model("sk-owners-own", structured=False)
    user_models[OWNER] = {owners.id: owners}
    engine = _engine()
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    with pytest.raises(ValueError, match="does not support structured output"):
        list(engine._execute_agent_node(_node(owners.id, json_schema=schema)))
    assert built_agents == []
