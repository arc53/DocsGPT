"""A headless run replaying a compressed conversation carries the summary the history was cut to."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _agent_kwargs(monkeypatch, events=None, outcome=None, **run_kwargs) -> dict:
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter(events or [{"answer": "ok"}])
    agent.llm.token_usage = {}
    retriever = MagicMock(search=MagicMock(return_value=[]))
    created: dict = {}

    def _create_agent(cls, type_, *args, **kwargs):
        created.update(kwargs)
        return agent

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever", classmethod(lambda cls, *a, **kw: retriever))
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[]))
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(_create_agent))
    monkeypatch.setattr(hr.QuotaService, "check", lambda *a, **kw: None)
    config = {"user_id": "u1", "id": "agent-1", "default_model_id": "m", "agent_type": "classic"}
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
            patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
            patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
            patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        result = hr.run_agent_headless(config, "do the thing", **run_kwargs)
    if outcome is not None:
        outcome.update(result)
    return created


@pytest.mark.unit
class TestHeadlessCompressedSummary:
    def test_the_summary_reaches_the_agent(self, monkeypatch):
        kwargs = _agent_kwargs(monkeypatch, compressed_summary="Earlier turns, summarized.")
        assert kwargs["compressed_summary"] == "Earlier turns, summarized."

    def test_no_summary_by_default(self, monkeypatch):
        assert _agent_kwargs(monkeypatch).get("compressed_summary") is None


@pytest.mark.unit
class TestHeadlessResponsesMetadata:
    def test_the_turns_responses_metadata_is_returned(self, monkeypatch):
        """A continuation stores it, so the user's next turn can chain onto this one."""
        outcome: dict = {}
        events = [
            {"answer": "done"},
            {"metadata": {"response_id": "resp_1", "responses_state": {"chain_key": "k"}}},
            {"metadata": {"usage": {"prompt_tokens": 10}}},
        ]
        _agent_kwargs(monkeypatch, events=events, outcome=outcome)
        assert outcome["metadata"] == {
            "response_id": "resp_1", "responses_state": {"chain_key": "k"}, "usage": {"prompt_tokens": 10}
        }
