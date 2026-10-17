"""``run_agent_headless`` renders only a prompt the agent's owner may use.

Scheduled and webhook runs execute as the owner; a prompt the owner lost
access to (a revoked team grant, a deleted prompt) falls back to the default.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

PROMPT_ID = "11111111-1111-1111-1111-111111111111"


def _rendered_prompt_id(monkeypatch, *, usable: bool) -> str:
    from docsgpt.agents import headless_runner as hr
    from docsgpt.api.user.resource_access import build

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}
    retriever = MagicMock(name="retriever")
    retriever.search.return_value = []
    tool_executor = MagicMock(name="tool_executor")
    tool_executor.headless_denials = []
    rendered: list = []

    def _get_prompt(pid):
        rendered.append(pid)
        return "system prompt"

    seen: list = []

    def _resolve(_conn, resource_type, resource_id, user_id):
        seen.append((resource_type, resource_id, user_id))
        return build(resource_type, resource_id, "viewer", "x", {}) if usable else None

    @contextmanager
    def _conn():
        yield MagicMock()

    monkeypatch.setattr(hr, "get_prompt", _get_prompt)
    monkeypatch.setattr(
        hr.RetrieverCreator, "create_retriever",
        classmethod(lambda cls, *a, **kw: retriever),
    )
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
    monkeypatch.setattr(
        hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: agent),
    )
    config = {
        "user_id": "owner-1", "id": "agent-1", "default_model_id": "m",
        "prompt_id": PROMPT_ID,
    }
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
         patch("docsgpt.core.model_utils.get_default_model_id", return_value="m"), \
         patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
         patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000), \
         patch("docsgpt.api.user.resource_access.resolve", _resolve), \
         patch("docsgpt.api.answer.services.stream_processor.db_readonly", _conn):
        hr.run_agent_headless(config, "do the thing")
    # Checked as the agent's owner, not whoever scheduled the run.
    assert seen == [("prompt", PROMPT_ID, "owner-1")]
    return rendered[0]


@pytest.mark.unit
class TestHeadlessRunnerPromptAccess:
    def test_usable_prompt_is_rendered(self, monkeypatch):
        assert _rendered_prompt_id(monkeypatch, usable=True) == PROMPT_ID

    def test_unusable_prompt_falls_back_to_default(self, monkeypatch):
        assert _rendered_prompt_id(monkeypatch, usable=False) == "default"
