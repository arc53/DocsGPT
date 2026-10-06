"""A webhook or scheduled run of an agent gets exactly the agent's tools.

A draft agent has no API key, and the executor used to fall back to the
owner's agentless chat toolset for it, so a draft with no tools could call
the owner's Telegram bot from its webhook.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


def _run(agent_row, pg_conn, monkeypatch, events=None, **extra):
    """Run ``agent_row`` headless; return the executor and the prompt's ``enabled_tools``."""
    from docsgpt.agents import headless_runner as hr

    @contextmanager
    def _use_pg_conn():
        yield pg_conn

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter(events or [{"answer": "ok"}])
    agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}
    built: dict = {}
    rendered: dict = {}

    def _create_agent(cls, *args, **kwargs):
        built.update(kwargs)
        return agent

    def _render(self, **kwargs):
        rendered.update(kwargs)
        return "prompt"

    monkeypatch.setattr("docsgpt.agents.tool_executor.db_readonly", _use_pg_conn)
    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(_create_agent))
    monkeypatch.setattr(hr.PromptRenderer, "render_prompt", _render)
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
         patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
         patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000), \
         patch("docsgpt.agents.headless_runner.QuotaService.check", return_value=None):
        built["outcome"] = hr.run_agent_headless(agent_row, '{"event": "push"}', endpoint="webhook", **extra)
    return built["tool_executor"], rendered["enabled_tools"]


@pytest.mark.unit
class TestHeadlessRunnerTools:
    def test_draft_agent_without_tools_gets_none_of_the_owners(self, pg_conn, monkeypatch):
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        UserToolsRepository(pg_conn).create(user_id="owner-1", name="telegram", status=True)
        row = AgentsRepository(pg_conn).create(
            user_id="owner-1", name="draft", status="draft", tools=[], default_model_id="m",
        )
        assert row.get("key") is None

        executor, enabled = _run(row, pg_conn, monkeypatch)
        assert executor.get_tools() == {}
        assert enabled == set()

    def test_draft_agent_gets_its_own_tools(self, pg_conn, monkeypatch):
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        repo = UserToolsRepository(pg_conn)
        own = repo.create(user_id="owner-1", name="ntfy", status=True)
        repo.create(user_id="owner-1", name="telegram", status=True)
        row = AgentsRepository(pg_conn).create(
            user_id="owner-1", name="draft", status="draft", tools=[str(own["id"])],
            default_model_id="m",
        )

        executor, enabled = _run(row, pg_conn, monkeypatch)
        assert set(executor.get_tools()) == {str(own["id"])}
        assert enabled == {"ntfy"}


@pytest.mark.unit
def test_a_continuation_turn_runs_as_its_message_and_can_hand_off(pg_conn, monkeypatch):
    """A woken turn binds its reserved message and background context; approval stays headless (denied)."""
    from docsgpt.background.context import BackgroundContext
    from docsgpt.storage.db.repositories.agents import AgentsRepository

    row = AgentsRepository(pg_conn).create(
        user_id="owner-1", name="a", status="draft", tools=[], default_model_id="m",
    )
    context = BackgroundContext(user_id="owner-1", conversation_id="c1", origin_message_id="m-9", continuation=True)
    executor, _ = _run(row, pg_conn, monkeypatch, conversation_id="c1", message_id="m-9", background=context)
    assert executor.message_id == "m-9"
    assert executor.background is context
    assert executor.headless is True


@pytest.mark.unit
def test_other_headless_runs_have_no_background_context(pg_conn, monkeypatch):
    from docsgpt.storage.db.repositories.agents import AgentsRepository

    row = AgentsRepository(pg_conn).create(
        user_id="owner-1", name="a", status="draft", tools=[], default_model_id="m",
    )
    executor, _ = _run(row, pg_conn, monkeypatch)
    assert executor.background is None
    assert executor.message_id is None


@pytest.mark.unit
def test_text_after_a_tool_call_starts_a_new_paragraph(pg_conn, monkeypatch):
    """A woken turn's or a scheduled run's stored answer reads like a chat turn's, never glued."""
    from docsgpt.agents import headless_runner as hr
    from docsgpt.storage.db.repositories.agents import AgentsRepository

    row = AgentsRepository(pg_conn).create(
        user_id="owner-1", name="a", status="draft", tools=[], default_model_id="m",
    )
    outcomes = []
    real = hr.run_agent_headless

    def capture(*args, **kwargs):
        outcomes.append(real(*args, **kwargs))
        return outcomes[-1]

    monkeypatch.setattr(hr, "run_agent_headless", capture)
    events = [
        {"answer": "I'll check the page."},
        {"type": "tool_call", "data": {"call_id": "c1", "status": "pending"}},
        {"answer": "It says 42."},
    ]
    _run(row, pg_conn, monkeypatch, events=events)
    assert outcomes[0]["answer"] == "I'll check the page.\n\nIt says 42."
