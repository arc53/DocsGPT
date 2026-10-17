"""A decision for a pause that is no longer waiting is refused, and never runs or denies another pause."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

CONV_ID = "00000000-0000-0000-0000-000000000001"


def _state(pending_ids):
    return {
        "messages": [],
        "pending_tool_calls": [{"call_id": cid, "name": "act", "arguments": {}} for cid in pending_ids],
        "tools_dict": {},
        "tool_schemas": [],
        "agent_config": {
            "model_id": "m1",
            "llm_name": "openai",
            "api_key": "k",
            "agent_type": "ClassicAgent",
            "reserved_message_id": "22222222-2222-2222-2222-222222222222",
        },
        "client_tools": None,
    }


@pytest.fixture()
def resume(monkeypatch):
    """A processor whose resume runs against a mocked continuation service."""
    from docsgpt.agents import agent_creator as ac_mod
    from docsgpt.agents import tool_executor as te_mod
    from docsgpt.api.answer.services import continuation_service as cont_mod
    from docsgpt.api.answer.services import stream_processor as sp_mod
    from docsgpt.llm import llm_creator as llm_creator_mod
    from docsgpt.llm.handlers import handler_creator as handler_mod

    service = MagicMock()
    monkeypatch.setattr(cont_mod, "ContinuationService", lambda: service)
    monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(te_mod, "ToolExecutor", lambda **kw: MagicMock(client_tools=None))
    monkeypatch.setattr(ac_mod.AgentCreator, "create_agent", lambda *a, **kw: MagicMock())

    sp = sp_mod.StreamProcessor.__new__(sp_mod.StreamProcessor)
    sp.data = {}
    sp.decoded_token = {"sub": "alice"}
    sp.initial_user_id = "alice"
    sp.conversation_id = CONV_ID
    sp.agent_config = {}
    sp.reserved_message_id = None
    return sp, service


class TestResumeRefusesWhatIsNotPending:
    def test_nothing_left_to_claim_is_not_pending(self, resume):
        from docsgpt.api.answer.services.continuation_service import (
            NOT_PENDING_MESSAGE,
            ContinuationNotPendingError,
        )

        sp, service = resume
        service.claim_state.return_value = None

        with pytest.raises(ContinuationNotPendingError) as raised:
            sp.resume_from_tool_actions([{"call_id": "call-5", "decision": "approved"}], CONV_ID)

        assert str(raised.value) == NOT_PENDING_MESSAGE
        # Still a ValueError for callers that catch the old error.
        assert isinstance(raised.value, ValueError)

    def test_a_decision_for_another_pause_is_refused_and_the_claim_returned(self, resume):
        """A stale tab approving an abandoned call must not resolve (and deny) a later pause."""
        from docsgpt.api.answer.services.continuation_service import ContinuationNotPendingError

        sp, service = resume
        service.claim_state.return_value = _state(["call-9"])

        with pytest.raises(ContinuationNotPendingError):
            sp.resume_from_tool_actions([{"call_id": "call-5", "decision": "approved"}], CONV_ID)

        service.release_claim.assert_called_once_with(CONV_ID, "alice")

    def test_a_decision_for_this_pause_resumes(self, resume):
        sp, service = resume
        service.claim_state.return_value = _state(["call-5", "call-6"])

        result = sp.resume_from_tool_actions([{"call_id": "call-5", "decision": "approved"}], CONV_ID)

        assert result[3][0]["call_id"] == "call-5"
        service.release_claim.assert_not_called()


@pytest.fixture
def stream_processor_mock():
    with patch("docsgpt.api.answer.routes.stream.StreamProcessor") as processor_cls:
        processor = MagicMock()
        processor.decoded_token = {"sub": "test_user"}
        processor_cls.return_value = processor
        yield processor


@pytest.fixture
def stream_client(mock_mongo_db, flask_app):
    from flask_restx import Api

    from docsgpt.api.answer.routes.stream import answer_ns

    api = Api(flask_app)
    api.add_namespace(answer_ns)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def answer_processor_mock():
    with patch("docsgpt.api.answer.routes.answer.StreamProcessor") as processor_cls:
        processor = MagicMock()
        processor.decoded_token = {"sub": "test_user"}
        processor_cls.return_value = processor
        yield processor


@pytest.fixture
def answer_client(mock_mongo_db, flask_app):
    from flask_restx import Api

    from docsgpt.api.answer.routes.answer import answer_ns

    api = Api(flask_app)
    api.add_namespace(answer_ns)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


RESUME_BODY = {
    "question": "",
    "conversation_id": "507f1f77bcf86cd799439011",
    "tool_actions": [{"call_id": "call-5", "decision": "approved"}],
}


@pytest.mark.unit
class TestRoutesAnswerALateDecision:
    def test_stream_answers_409_with_a_code(self, stream_client, stream_processor_mock):
        from docsgpt.api.answer.services.continuation_service import (
            NOT_PENDING_MESSAGE,
            ContinuationNotPendingError,
        )

        stream_processor_mock.resume_from_tool_actions.side_effect = ContinuationNotPendingError(
            NOT_PENDING_MESSAGE
        )
        with patch("docsgpt.api.answer.routes.stream.StreamResource.validate_request", return_value=None):
            resp = stream_client.post("/stream", data=json.dumps(RESUME_BODY), content_type="application/json")

        assert resp.status_code == 409
        assert "text/event-stream" in resp.content_type
        payload = json.loads(resp.get_data(as_text=True).split("data: ", 1)[1])
        assert payload == {"type": "error", "error": NOT_PENDING_MESSAGE, "code": "tool_call_not_pending"}

    def test_answer_answers_409_with_a_code(self, answer_client, answer_processor_mock):
        from docsgpt.api.answer.services.continuation_service import (
            NOT_PENDING_MESSAGE,
            ContinuationNotPendingError,
        )

        answer_processor_mock.resume_from_tool_actions.side_effect = ContinuationNotPendingError(
            NOT_PENDING_MESSAGE
        )
        with patch("docsgpt.api.answer.routes.answer.AnswerResource.validate_request", return_value=None):
            resp = answer_client.post("/api/answer", data=json.dumps(RESUME_BODY), content_type="application/json")

        assert resp.status_code == 409
        assert resp.get_json() == {"error": NOT_PENDING_MESSAGE, "code": "tool_call_not_pending"}
