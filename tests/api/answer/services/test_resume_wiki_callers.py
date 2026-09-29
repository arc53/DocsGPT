"""A resumed turn keeps the wiki and write rules of whoever resumes it.

Continuation state is looked up by the agent owner, so a request carrying the
agent's key (a widget key is public) could resume the owner's own paused chat.
The resumed run counts as an outside caller when either the saved state or the
resuming request says so, and a request may only resume a turn of the agent it
names.
"""

from __future__ import annotations

import copy
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

AGENT = "11111111-1111-1111-1111-111111111111"
OTHER_AGENT = "22222222-2222-2222-2222-222222222222"
OWNER = "owner"


def _wiki_entry(**config):
    from docsgpt.agents.tools.wiki import WIKI_TOOL_ID, add_wiki_tool

    tools = {}
    add_wiki_tool(tools, {"source_id": "wiki-1", "source_owner_id": OWNER, "user": OWNER, **config})
    return tools[WIKI_TOOL_ID]


def _state(agent_id=AGENT, **flags):
    return {
        "messages": [],
        "pending_tool_calls": [],
        "tools_dict": {"wiki": _wiki_entry()},
        "tool_schemas": [],
        "client_tools": None,
        "agent_config": {
            "model_id": "m1", "llm_name": "openai", "api_key": "k", "user_api_key": "agent-key",
            "agent_type": "ClassicAgent", "agent_id": agent_id, **flags,
        },
    }


@pytest.fixture
def resume(monkeypatch):
    """Resume a saved state; returns (tools_dict, executor, continuation service)."""
    from docsgpt.agents import agent_creator as ac_mod
    from docsgpt.api.answer.services import continuation_service as cont_mod
    from docsgpt.api.answer.services import stream_processor as sp_mod
    from docsgpt.llm import llm_creator as llm_creator_mod
    from docsgpt.llm.handlers import handler_creator as handler_mod

    @contextmanager
    def _noop():
        yield None

    agents = {"agent-key": {"id": AGENT, "user_id": OWNER}, "other-key": {"id": OTHER_AGENT, "user_id": OWNER}}

    class _Agents:
        def __init__(self, conn):
            pass

        def find_by_key(self, key):
            return agents.get(key)

    live = {"allowed": False}

    class _Sources:
        def __init__(self, conn):
            pass

        def get_by_id(self, sid):
            return {"id": sid, "wiki_outside_edits": live["allowed"]}

    def _get_agent_key(self, agent_id, user_id):
        # Only the owner reaches the agent directly; anyone else by its link.
        self.public_link_usage = user_id != OWNER
        return "agent-key", user_id != OWNER, None

    monkeypatch.setattr(sp_mod.StreamProcessor, "_get_agent_key", _get_agent_key)
    monkeypatch.setattr(sp_mod, "db_readonly", _noop)
    monkeypatch.setattr(sp_mod, "AgentsRepository", _Agents)
    monkeypatch.setattr("docsgpt.agents.tools.wiki.db_readonly", _noop)
    monkeypatch.setattr("docsgpt.agents.tools.wiki.SourcesRepository", _Sources)
    monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
    created = {}
    monkeypatch.setattr(ac_mod.AgentCreator, "create_agent", lambda *a, **kw: created.update(kw) or MagicMock())

    def _run(state, data, token, *, external_caller=False, allowed=False):
        live["allowed"] = allowed
        cont_service = MagicMock()
        cont_service.claim_state.return_value = copy.deepcopy(state)
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        processor = sp_mod.StreamProcessor(data, token, external_caller=external_caller)
        result = processor.resume_from_tool_actions(tool_actions=[], conversation_id=str(uuid.uuid4()))
        return result[2], created["tool_executor"], cont_service

    return _run


def _actions(tools_dict):
    return [a["name"] for a in tools_dict["wiki"]["actions"]]


@pytest.mark.unit
class TestResumeByOutsideCaller:
    def test_widget_key_resuming_the_owners_chat_gets_read_only_wiki(self, resume):
        tools, executor, _ = resume(_state(), {"api_key": "agent-key"}, None)
        assert executor.external_caller is True
        assert _actions(tools) == ["wiki_view"]
        assert tools["wiki"]["config"]["outside_caller"] is True

    def test_signed_in_stranger_with_the_key_is_outside(self, resume):
        tools, executor, _ = resume(_state(), {"api_key": "agent-key"}, {"sub": "stranger"})
        assert executor.external_caller is True
        assert _actions(tools) == ["wiki_view"]

    def test_edits_stay_when_the_wiki_allows_them(self, resume):
        tools, executor, _ = resume(_state(), {"api_key": "agent-key"}, None, allowed=True)
        assert executor.external_caller is True
        assert "wiki_create" in _actions(tools)
        # The tool still re-checks the live setting on every write.
        assert tools["wiki"]["config"]["outside_caller"] is True

    def test_v1_key_holder_is_outside(self, resume):
        tools, executor, _ = resume(_state(), {"api_key": "agent-key"}, {"sub": OWNER}, external_caller=True)
        assert executor.external_caller is True
        assert _actions(tools) == ["wiki_view"]

    def test_saved_outside_state_stays_outside_for_the_owner(self, resume):
        tools, executor, _ = resume(_state(external_api_caller=True), {}, {"sub": OWNER})
        assert executor.external_caller is True
        assert _actions(tools) == ["wiki_view"]

    def test_owner_resuming_in_app_is_unaffected(self, resume):
        tools, executor, _ = resume(_state(), {}, {"sub": OWNER})
        assert executor.external_caller is False
        assert executor.public_link_caller is False
        assert "wiki_create" in _actions(tools)
        assert tools["wiki"]["config"]["outside_caller"] is False

    def test_owner_previewing_with_the_key_is_unaffected(self, resume):
        tools, executor, _ = resume(_state(), {"api_key": "agent-key"}, {"sub": OWNER})
        assert executor.external_caller is False
        assert "wiki_create" in _actions(tools)


@pytest.mark.unit
class TestResumeTargetsTheSameAgent:
    def test_a_key_for_another_agent_is_refused(self, resume):
        with pytest.raises(ValueError):
            resume(_state(), {"api_key": "other-key"}, None)

    def test_release_on_refusal(self, resume, monkeypatch):
        from docsgpt.api.answer.services import continuation_service as cont_mod
        from docsgpt.api.answer.services import stream_processor as sp_mod

        cont_service = MagicMock()
        cont_service.claim_state.return_value = _state()
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        processor = sp_mod.StreamProcessor({"api_key": "other-key"}, None)
        conversation_id = str(uuid.uuid4())
        with pytest.raises(ValueError):
            processor.resume_from_tool_actions(tool_actions=[], conversation_id=conversation_id)
        cont_service.release_claim.assert_called_once_with(conversation_id, OWNER)

    def test_a_key_cannot_resume_an_agentless_chat(self, resume):
        with pytest.raises(ValueError):
            resume(_state(agent_id=None), {"api_key": "agent-key"}, None)

    def test_a_named_agent_must_match(self, resume):
        with pytest.raises(ValueError):
            resume(_state(), {"agent_id": OTHER_AGENT}, {"sub": OWNER})

    def test_same_agent_passes(self, resume):
        tools, _executor, _ = resume(_state(), {"agent_id": AGENT.upper()}, {"sub": OWNER})
        assert "wiki_create" in _actions(tools)


@pytest.mark.unit
class TestResumePublicLink:
    def test_saved_public_link_run_keeps_wiki_writes_behind_approval(self, resume):
        state = _state(public_link_caller=True)
        tools, executor, _ = resume(state, {}, {"sub": "visitor"})
        assert executor.public_link_caller is True
        writes = [a for a in tools["wiki"]["actions"] if a["name"] != "wiki_view"]
        assert writes and all(a.get("require_approval") for a in writes)
        view = next(a for a in tools["wiki"]["actions"] if a["name"] == "wiki_view")
        assert not view.get("require_approval")
        # Public-link visitors aren't covered by the switch.
        assert tools["wiki"]["config"]["outside_caller"] is False

    def test_a_request_naming_the_agent_by_its_link_is_public(self, resume):
        tools, executor, _ = resume(_state(), {"agent_id": AGENT}, {"sub": "visitor"})
        assert executor.public_link_caller is True
        assert all(
            a.get("require_approval") for a in tools["wiki"]["actions"] if a["name"] != "wiki_view"
        )
