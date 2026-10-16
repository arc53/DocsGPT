"""A headless run tells its agent what started it, for a workflow run to record."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _started_by(monkeypatch, **kwargs):
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.started_by = None
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {}
    retriever = MagicMock(search=MagicMock(return_value=[]))

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever", classmethod(lambda cls, *a, **kw: retriever))
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[]))
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: agent))
    monkeypatch.setattr(hr.QuotaService, "check", lambda *a, **kw: None)
    config = {"user_id": "u1", "id": "agent-1", "default_model_id": "m", "agent_type": "workflow"}
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
            patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
            patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
            patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        hr.run_agent_headless(config, "do the thing", **kwargs)
    return agent.started_by


@pytest.mark.unit
class TestHeadlessStartedBy:
    def test_a_scheduled_or_webhook_run_is_named_by_its_request_id(self, monkeypatch):
        # The scheduler passes its run id, the webhook worker its task id.
        assert _started_by(monkeypatch, request_id="run-1") == "run-1"

    def test_a_continuation_is_named_by_its_message(self, monkeypatch):
        assert _started_by(monkeypatch, request_id="req-1", message_id="msg-1") == "msg-1"

    def test_nothing_named_leaves_it_unset(self, monkeypatch):
        assert _started_by(monkeypatch) is None
