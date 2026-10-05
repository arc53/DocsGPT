"""A webhook or scheduled run of an agent gets exactly the agent's tools.

A draft agent has no API key, and the executor used to fall back to the
owner's agentless chat toolset for it, so a draft with no tools could call
the owner's Telegram bot from its webhook.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


def _run(agent_row, pg_conn, monkeypatch):
    """Run ``agent_row`` headless; return the executor and the prompt's ``enabled_tools``."""
    from docsgpt.agents import headless_runner as hr

    @contextmanager
    def _use_pg_conn():
        yield pg_conn

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
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
        hr.run_agent_headless(agent_row, '{"event": "push"}', endpoint="webhook")
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
