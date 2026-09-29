"""``run_agent_headless`` holds a run for an outside caller to the write allowlist.

Webhooks, schedules set through the API, and schedules a public-link user
set all run as the owner, but nobody behind them can approve for the owner.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _executor_kwargs(monkeypatch, config_extra=None, agent_kwargs=None, **run_kwargs):
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {}
    retriever = MagicMock(search=MagicMock(return_value=[]))
    captured = {}

    def _executor(*_args, **kwargs):
        captured.update(kwargs)
        return MagicMock(headless_denials=[])

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever", classmethod(lambda cls, *a, **kw: retriever))
    monkeypatch.setattr(hr, "ToolExecutor", _executor)
    def _create_agent(cls, *_args, **kwargs):
        if agent_kwargs is not None:
            agent_kwargs.update(kwargs)
        return agent

    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(_create_agent))
    monkeypatch.setattr(hr.QuotaService, "check", lambda *a, **kw: None)
    config = {"user_id": "u1", "id": "agent-1", "default_model_id": "m", **(config_extra or {})}
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
            patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
            patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
            patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        hr.run_agent_headless(config, "do the thing", **run_kwargs)
    return captured


@pytest.mark.unit
class TestHeadlessCallerRules:
    def test_owner_run_has_no_outside_caller(self, monkeypatch):
        kwargs = _executor_kwargs(monkeypatch)
        assert kwargs.get("external_caller") is False
        assert kwargs.get("public_link_caller") is False

    @pytest.mark.parametrize("flag", ["external_caller", "public_link_caller"])
    def test_outside_caller_carries_the_agents_allowlist(self, monkeypatch, flag):
        config = {"config": {"api_write_allowlist": ["tool-1:send"]}}
        kwargs = _executor_kwargs(monkeypatch, config, **{flag: True})
        assert kwargs[flag] is True
        assert kwargs["api_write_allowlist"] == ["tool-1:send"]

    @pytest.mark.parametrize("flag", ["external_caller", "public_link_caller"])
    def test_outside_caller_run_gets_no_wiki_editor(self, monkeypatch, flag):
        # A scheduled or webhook run has no wiki tool at all, so an outside
        # caller's schedule can't edit a wiki whatever the wiki allows.
        agent_kwargs = {}
        _executor_kwargs(monkeypatch, agent_kwargs=agent_kwargs, **{flag: True})
        assert agent_kwargs
        assert "wiki_config" not in agent_kwargs
