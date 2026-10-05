"""A resumed turn keeps the paused turn's sources and their ``[n]`` numbers.

The paused turn's documents were shown to the model as ``[1]..[k]``; the
resumed agent starts from them, so a hit found after the resume is ``[k+1]``
and the answer's source list still lines up with what the model cited.
"""

from __future__ import annotations

import copy
import uuid
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

DOC = {"title": "a.pdf", "source": "a.pdf", "text": "full passage", "chunk_key": "k"}


def _state(**agent_config) -> dict:
    return {
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}],
        "pending_tool_calls": [
            {"call_id": "call_1", "name": "search", "tool_name": "search", "llm_name": "search", "arguments": {}}
        ],
        "tools_dict": {},
        "tool_schemas": [],
        "agent_config": {
            "model_id": "gpt-test",
            "llm_name": "openai",
            "api_key": "k",
            "agent_type": "ClassicAgent",
            "prompt": "sys",
            **agent_config,
        },
    }


@pytest.fixture
def resume_kwargs(monkeypatch):
    """Resume a saved state; returns the kwargs the agent was built with."""
    from docsgpt.agents import agent_creator as ac_mod
    from docsgpt.api.answer.services import continuation_service as cont_mod
    from docsgpt.api.answer.services import stream_processor as sp_mod
    from docsgpt.llm import llm_creator as llm_creator_mod
    from docsgpt.llm.handlers import handler_creator as handler_mod

    def _run(state: dict) -> dict:
        cont_service = MagicMock()
        cont_service.claim_state.return_value = copy.deepcopy(state)
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
        created: dict = {}
        monkeypatch.setattr(
            ac_mod.AgentCreator, "create_agent", lambda *a, **kw: created.update(kw) or MagicMock(),
        )
        processor = sp_mod.StreamProcessor({}, {"sub": "owner"})
        processor.resume_from_tool_actions(
            tool_actions=[{"call_id": "call_1", "result": "ok"}],
            conversation_id=str(uuid.uuid4()),
        )
        return created

    return _run


def test_the_paused_turns_sources_seed_the_resumed_agent(resume_kwargs):
    kwargs = resume_kwargs(_state(retrieved_docs=[DOC]))
    assert kwargs["retrieved_docs"] == [DOC]


def test_a_state_saved_before_sources_were_kept_resumes_without_them(resume_kwargs):
    kwargs = resume_kwargs(_state())
    assert not kwargs.get("retrieved_docs")
