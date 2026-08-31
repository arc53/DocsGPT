"""``run_agent_headless`` must bind a workflow agent to its workflow.

Regression (prod 2026-08-06): the streaming path passes ``workflow_id`` /
``workflow_owner`` into ``AgentCreator.create_agent`` (see
``StreamProcessor``), but the headless path never did. A schedule or webhook
bound to a workflow agent therefore built ``WorkflowAgent(workflow_id=None)``,
``_load_workflow_graph()`` returned ``None``, and the agent's whole run was a
single ``{"type": "error", "error": "Failed to load workflow configuration."}``
— which the runner then dropped, so the schedule recorded ``success`` with no
output for as long as the schedule existed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _run(agent_config, monkeypatch, events=None):
    """Drive ``run_agent_headless`` and capture the agent-factory kwargs."""
    from application.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter(events if events is not None else [{"answer": "ok"}])
    agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}

    captured = {}

    def _create_agent(cls, agent_type, **kwargs):
        captured["agent_type"] = agent_type
        captured.update(kwargs)
        return agent

    retriever = MagicMock(name="retriever")
    retriever.search.return_value = []

    tool_executor = MagicMock(name="tool_executor")
    tool_executor.headless_denials = []

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(
        hr.RetrieverCreator, "create_retriever",
        classmethod(lambda cls, *a, **kw: retriever),
    )
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
    monkeypatch.setattr(
        hr.AgentCreator, "create_agent", classmethod(_create_agent),
    )

    with patch("application.core.model_utils.validate_model_id", return_value=True), \
         patch("application.core.model_utils.get_default_model_id", return_value="m"), \
         patch(
             "application.core.model_utils.get_provider_from_model_id",
             return_value="openai",
         ), \
         patch("application.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("application.utils.calculate_doc_token_budget", return_value=1000):
        outcome = hr.run_agent_headless(agent_config, "do the thing")
    return captured, outcome


@pytest.mark.unit
class TestHeadlessWorkflowBinding:
    def test_workflow_agent_receives_workflow_id_and_owner(self, monkeypatch):
        """The PG ``agents.workflow_id`` column must reach the agent."""
        captured, _ = _run(
            {
                "user_id": "u1",
                "id": "agent-1",
                "agent_type": "workflow",
                "workflow_id": "0f0c4b9e-1111-2222-3333-444455556666",
                "default_model_id": "m",
            },
            monkeypatch,
        )

        assert captured["agent_type"] == "workflow"
        assert captured["workflow_id"] == "0f0c4b9e-1111-2222-3333-444455556666"
        # Without an owner the repository lookup is unscoped and returns nothing.
        assert captured["workflow_owner"] == "u1"

    def test_legacy_workflow_key_also_binds(self, monkeypatch):
        """Legacy Mongo shape stored the reference under ``workflow``."""
        captured, _ = _run(
            {
                "user_id": "u1",
                "id": "agent-1",
                "agent_type": "workflow",
                "workflow": "wf-legacy-ref",
                "default_model_id": "m",
            },
            monkeypatch,
        )

        assert captured["workflow_id"] == "wf-legacy-ref"
        assert captured["workflow_owner"] == "u1"

    def test_embedded_graph_is_passed_as_workflow(self, monkeypatch):
        """An inline graph goes to ``workflow=``, not stringified into an id."""
        graph = {"name": "inline", "nodes": [], "edges": []}
        captured, _ = _run(
            {
                "user_id": "u1",
                "id": "agent-1",
                "agent_type": "workflow",
                "workflow": graph,
                "default_model_id": "m",
            },
            monkeypatch,
        )

        assert captured["workflow"] == graph
        assert "workflow_id" not in captured
        assert captured["workflow_owner"] == "u1"

    def test_non_workflow_agent_gets_no_workflow_kwargs(self, monkeypatch):
        """``ClassicAgent`` has no such kwargs; passing them would TypeError."""
        captured, _ = _run(
            {
                "user_id": "u1",
                "id": "agent-1",
                "agent_type": "classic",
                "workflow_id": "should-be-ignored",
                "default_model_id": "m",
            },
            monkeypatch,
        )

        assert "workflow_id" not in captured
        assert "workflow" not in captured
        assert "workflow_owner" not in captured

    def test_workflow_steps_are_counted_as_work(self, monkeypatch):
        """Completed nodes are the workflow's proof of work.

        A workflow's tool calls never reach the caller as ``tool_calls``
        events (the engine keeps them in its execution log) and its node
        agents carry their own LLMs, so the runner's token tally is 0. Without
        a step count, a side-effecting workflow looks identical to one that
        did nothing at all.
        """
        _, outcome = _run(
            {
                "user_id": "u1",
                "id": "agent-1",
                "agent_type": "workflow",
                "workflow_id": "wf-1",
                "default_model_id": "m",
            },
            monkeypatch,
            events=[
                {"type": "workflow_step", "node_id": "n1", "status": "running"},
                {"type": "workflow_step", "node_id": "n1", "status": "completed"},
                {"type": "workflow_step", "node_id": "n2", "status": "completed"},
            ],
        )

        assert outcome["steps_completed"] == 2
        assert outcome["error_type"] is None

    def test_failed_steps_are_not_counted(self, monkeypatch):
        _, outcome = _run(
            {
                "user_id": "u1",
                "id": "agent-1",
                "agent_type": "workflow",
                "workflow_id": "wf-1",
                "default_model_id": "m",
            },
            monkeypatch,
            events=[
                {"type": "workflow_step", "node_id": "n1", "status": "failed"},
                {"type": "error", "error": "Node http_1: connection refused"},
            ],
        )

        assert outcome["steps_completed"] == 0
        assert outcome["error_type"] == "stream_error"
