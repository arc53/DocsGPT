"""Resuming a turn paused on clarifying questions (``ask_user``): the action rules and the restored question state."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

CONV_ID = "00000000-0000-0000-0000-000000000001"


def _state(pause_type: str = "awaiting_answer", **agent_config):
    return {
        "messages": [],
        "pending_tool_calls": [{"call_id": "c1", "name": "ask_user", "arguments": {}, "pause_type": pause_type}],
        "tools_dict": {},
        "tool_schemas": [],
        "agent_config": {
            "model_id": "m1",
            "llm_name": "openai",
            "api_key": "k",
            "agent_type": "ClassicAgent",
            "reserved_message_id": "22222222-2222-2222-2222-222222222222",
            **agent_config,
        },
        "client_tools": None,
    }


@pytest.fixture()
def resume(monkeypatch):
    """A processor whose resume runs against a mocked continuation service; the built executor is kept."""
    from docsgpt.agents import agent_creator as ac_mod
    from docsgpt.agents import tool_executor as te_mod
    from docsgpt.api.answer.services import continuation_service as cont_mod
    from docsgpt.api.answer.services import stream_processor as sp_mod
    from docsgpt.llm import llm_creator as llm_creator_mod
    from docsgpt.llm.handlers import handler_creator as handler_mod

    service = MagicMock()
    built = {}

    def make_executor(**kw):
        built["executor"] = MagicMock(client_tools=None, offers_questions=False, questions_asked=False)
        return built["executor"]

    monkeypatch.setattr(cont_mod, "ContinuationService", lambda: service)
    monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(te_mod, "ToolExecutor", make_executor)
    monkeypatch.setattr(ac_mod.AgentCreator, "create_agent", lambda *a, **kw: MagicMock())

    sp = sp_mod.StreamProcessor.__new__(sp_mod.StreamProcessor)
    sp.data = {}
    sp.decoded_token = {"sub": "alice"}
    sp.initial_user_id = "alice"
    sp.conversation_id = CONV_ID
    sp.agent_config = {}
    sp.reserved_message_id = None
    return sp, service, built


class TestQuestionActions:
    def test_an_answer_resumes(self, resume):
        sp, service, _built = resume
        service.claim_state.return_value = _state(questions=True)

        result = sp.resume_from_tool_actions([{"call_id": "c1", "answer": "Team size? → 11-50"}], CONV_ID)

        assert result[4] == [{"call_id": "c1", "answer": "Team size? → 11-50"}]
        service.release_claim.assert_not_called()

    def test_a_decision_on_a_question_is_malformed_and_the_claim_returned(self, resume):
        sp, service, _built = resume
        service.claim_state.return_value = _state()

        with pytest.raises(ValueError):
            sp.resume_from_tool_actions([{"call_id": "c1", "decision": "approved"}], CONV_ID)
        service.release_claim.assert_called_once_with(CONV_ID, "alice")

    def test_an_answer_to_an_approval_is_malformed(self, resume):
        sp, service, _built = resume
        service.claim_state.return_value = _state(pause_type="awaiting_approval")

        with pytest.raises(ValueError):
            sp.resume_from_tool_actions([{"call_id": "c1", "answer": "yes"}], CONV_ID)
        service.release_claim.assert_called_once_with(CONV_ID, "alice")


class TestRestoredQuestionState:
    # ``"cards"``: a turn paused before the saved offer became a bool.
    @pytest.mark.parametrize("saved", [True, "cards"])
    def test_a_resuming_client_that_renders_forms_keeps_the_questions(self, resume, saved):
        sp, service, built = resume
        sp.data = {"capabilities": ["forms"]}
        service.claim_state.return_value = _state(pause_type="awaiting_approval", questions=saved)

        sp.resume_from_tool_actions([{"call_id": "c1", "decision": "approved"}], CONV_ID)

        assert built["executor"].offers_questions is True
        assert built["executor"].questions_asked is False

    @pytest.mark.parametrize("data", [{}, {"capabilities": "forms"}, {"questions": "cards"}])
    def test_a_resuming_client_without_forms_gets_no_questions(self, resume, data):
        sp, service, built = resume
        sp.data = data
        service.claim_state.return_value = _state(pause_type="awaiting_approval", questions=True)

        sp.resume_from_tool_actions([{"call_id": "c1", "decision": "approved"}], CONV_ID)

        assert built["executor"].offers_questions is False

    @pytest.mark.parametrize("saved", [None, False])
    def test_a_turn_that_offered_no_questions_still_does_not(self, resume, saved):
        sp, service, built = resume
        sp.data = {"capabilities": ["forms"]}
        service.claim_state.return_value = _state(pause_type="awaiting_approval", questions=saved)

        sp.resume_from_tool_actions([{"call_id": "c1", "decision": "approved"}], CONV_ID)

        assert built["executor"].offers_questions is False

    def test_answering_the_questions_uses_the_turns_round(self, resume):
        sp, service, built = resume
        service.claim_state.return_value = _state(questions=True)

        sp.resume_from_tool_actions([{"call_id": "c1", "skipped": True}], CONV_ID)

        assert built["executor"].questions_asked is True

    def test_a_round_asked_before_an_approval_pause_is_remembered(self, resume):
        sp, service, built = resume
        service.claim_state.return_value = _state(
            pause_type="awaiting_approval", questions=True, questions_asked=True,
        )

        sp.resume_from_tool_actions([{"call_id": "c1", "decision": "approved"}], CONV_ID)

        assert built["executor"].questions_asked is True


class TestNewTurnQuestionMode:
    def _executor(self, agent_type: str, data: dict):
        from unittest.mock import patch

        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor(data, {"sub": "u1"})
        processor._get_prompt_content = MagicMock(return_value="prompt")
        processor.agent_config = {"agent_type": agent_type, "prompt_id": "custom", "user_api_key": None}
        processor.model_id = "m1"
        processor.prompt_renderer = MagicMock()
        create = MagicMock(return_value=MagicMock())
        with (
            patch("docsgpt.api.answer.services.stream_processor.get_provider_from_model_id", return_value="openai"),
            patch("docsgpt.api.answer.services.stream_processor.get_api_key_for_provider", return_value="key"),
            patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()),
            patch("docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler", return_value=MagicMock()),
            patch("docsgpt.agents.agent_creator.AgentCreator.create_agent", create),
            patch.object(StreamProcessor, "_enabled_tool_names", return_value=set()),
        ):
            processor.create_agent()
        return create.call_args.kwargs["tool_executor"]

    @pytest.mark.parametrize("data", [{"capabilities": ["forms"]}, {"capabilities": ["mermaid", "forms", 3]}])
    def test_a_client_that_renders_forms_gets_question_cards(self, data):
        assert self._executor("classic", data).offers_questions is True
        assert self._executor("agentic", data).offers_questions is True

    @pytest.mark.parametrize(
        "data",
        [{}, {"capabilities": []}, {"capabilities": "forms"}, {"capabilities": ["mermaid"]}, {"questions": "cards"}],
    )
    def test_a_client_without_forms_gets_no_questions(self, data):
        """API agents, the widget and bots send no capabilities: the turn runs as it did before questions."""
        assert self._executor("classic", data).offers_questions is False
        assert self._executor("agentic", data).offers_questions is False

    @pytest.mark.parametrize("agent_type", ["research", "workflow"])
    def test_research_and_workflow_agents_offer_none(self, agent_type):
        assert self._executor(agent_type, {"capabilities": ["forms"]}).offers_questions is False
