"""The turn's decision record: created by the processor, carried by the agent, stored on the message, kept over a
pause."""

from __future__ import annotations

import copy
import functools
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.agents.base import BaseAgent
from docsgpt.decisions import record
from docsgpt.decisions.testing import FakeDecider, installed

PENDING = [{"call_id": "c1", "name": "search", "tool_name": "search", "llm_name": "search", "arguments": {}}]


@pytest.fixture(autouse=True)
def _fake():
    with installed(FakeDecider()):
        yield


def _resource():
    from docsgpt.api.answer.routes.base import BaseAnswerResource

    resource = BaseAnswerResource()
    resource.conversation_service = MagicMock()
    resource.conversation_service.save_user_question.return_value = {"conversation_id": "c1", "message_id": "m1"}
    return resource


def _agent(gen=None, **attributes):
    agent = MagicMock()
    agent.tool_calls = []
    agent.compression_metadata = None
    agent.compression_saved = False
    agent.attachments = []
    agent.last_compression_at = None
    agent.paused_turn_state = functools.partial(BaseAgent.paused_turn_state, agent)
    if gen is not None:
        agent.gen.side_effect = gen
    for name, value in attributes.items():
        setattr(agent, name, value)
    return agent


def _deciding(feature, *events):
    def gen(*_args, **_kwargs):
        record.add(feature, {"p": 0.1}, status="ok", applied=False, ms=5.0)
        yield from events

    return gen


def _stream(resource, agent, **kwargs):
    base = dict(question="q", agent=agent, conversation_id=None, user_api_key=None,
                decoded_token={"sub": "u1"}, should_persist=True, model_id="gpt-4")
    return list(resource.complete_stream(**{**base, **kwargs}))


def _finalized(resource):
    return resource.conversation_service.finalize_message.call_args.kwargs.get("metadata") or {}


@pytest.mark.unit
class TestTheStream:
    def test_a_turn_that_asked_the_model_stores_its_record(self, flask_app, mock_mongo_db):
        resource = _resource()
        with flask_app.app_context():
            _stream(resource, _agent(_deciding("injection_input", {"answer": "hi"})))
        stored = _finalized(resource)["decisions"]
        assert stored["v"] == 1 and stored["dropped"] == 0
        assert [(e["feature"], e["round"], e["applied"]) for e in stored["entries"]] == [
            ("injection_input", 0, False)
        ]
        json.dumps(stored)

    def test_a_turn_that_did_not_stores_nothing(self, flask_app, mock_mongo_db):
        resource = _resource()
        with flask_app.app_context():
            _stream(resource, _agent(lambda *a, **k: iter([{"answer": "hi"}])))
        assert "decisions" not in _finalized(resource)

    def test_the_record_the_agent_carries_holds_setup_decisions(self, flask_app, mock_mongo_db):
        handed = record.DecisionRecord()
        handed.add("rag_rerank", {"kept": 4}, status="ok", applied=True)
        resource = _resource()
        with flask_app.app_context():
            _stream(resource, _agent(_deciding("injection_input", {"answer": "hi"}), decision_record=handed))
        assert [e["feature"] for e in _finalized(resource)["decisions"]["entries"]] == [
            "rag_rerank", "injection_input"
        ]

    def test_nothing_leaks_into_the_next_stream(self, flask_app, mock_mongo_db):
        with flask_app.app_context():
            _stream(_resource(), _agent(_deciding("injection_input", {"answer": "hi"})))
            resource = _resource()
            _stream(resource, _agent(lambda *a, **k: iter([{"answer": "hi"}])))
        assert "decisions" not in _finalized(resource)
        assert record.current() is None


@pytest.mark.unit
class TestTheProcessor:
    def test_setup_runs_inside_the_processors_record(self):
        from docsgpt.api.answer.services import stream_processor as sp_mod

        processor = sp_mod.StreamProcessor({}, {"sub": "u1"})
        assert sp_mod._traced_setup(lambda self: record.current())(processor) is processor.decision_record
        assert record.current() is None

    def test_the_agent_it_creates_carries_the_record(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({}, {"sub": "u1"})
        processor._get_prompt_content = MagicMock(return_value="prompt")
        processor.agent_config = {"agent_type": "classic", "prompt_id": "custom", "user_api_key": None}
        processor.model_id = "m1"
        processor.prompt_renderer = MagicMock()
        with (
            patch("docsgpt.api.answer.services.stream_processor.get_provider_from_model_id", return_value="openai"),
            patch("docsgpt.api.answer.services.stream_processor.get_api_key_for_provider", return_value="key"),
            patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()),
            patch("docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler", return_value=MagicMock()),
            patch("docsgpt.agents.agent_creator.AgentCreator.create_agent", return_value=MagicMock()),
            patch.object(StreamProcessor, "_enabled_tool_names", return_value=set()),
        ):
            agent = processor.create_agent()
        assert agent.decision_record is processor.decision_record

    def test_a_processor_built_without_init_still_has_one(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor.__new__(StreamProcessor)
        assert isinstance(processor.decision_record, record.DecisionRecord)
        assert processor.decision_record is processor.__dict__["decision_record"]  # made once, then kept


@pytest.fixture
def resume(monkeypatch):
    """Resume a saved pending state through the processor; returns the rebuilt agent and the processor."""
    from docsgpt.agents import agent_creator as ac_mod
    from docsgpt.api.answer.services import continuation_service as cont_mod
    from docsgpt.api.answer.services import stream_processor as sp_mod
    from docsgpt.llm import llm_creator as llm_creator_mod
    from docsgpt.llm.handlers import handler_creator as handler_mod

    def _run(state: dict, agent: MagicMock):
        cont_service = MagicMock()
        cont_service.claim_state.return_value = copy.deepcopy(state)
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(ac_mod.AgentCreator, "create_agent", lambda *a, **kw: agent)
        processor = sp_mod.StreamProcessor({}, {"sub": "u1"})
        processor.resume_from_tool_actions(
            tool_actions=[{"call_id": "c1", "result": "ok"}], conversation_id=str(uuid.uuid4())
        )
        return agent, processor

    return _run


def _pending_state(agent_config: dict) -> dict:
    return {
        "messages": [{"role": "user", "content": "q"}],
        "pending_tool_calls": PENDING,
        "tools_dict": {},
        "tool_schemas": [],
        "agent_config": {"model_id": "gpt-4", "llm_name": "openai", "api_key": "k", "agent_type": "ClassicAgent",
                         "prompt": "sys", **agent_config},
    }


@pytest.mark.unit
class TestPauseAndResume:
    def test_the_resume_continues_the_saved_record(self, resume):
        paused = record.DecisionRecord()
        paused.add("injection_input", {"p": 0.03}, status="ok", applied=False)
        agent, processor = resume(_pending_state({"decisions": paused.snapshot()}), _agent())
        assert agent.decision_record is processor.decision_record
        assert processor.decision_record.round == 1
        assert len(processor.decision_record.snapshot()["entries"]) == 1

    def test_a_paused_and_resumed_stream_stores_both_rounds(self, flask_app, mock_mongo_db, monkeypatch, resume):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        saved = {}
        monkeypatch.setattr(ContinuationService, "save_state", lambda self, **kw: saved.update(kw))
        paused_agent = _agent(_deciding("injection_input", {
            "type": "tool_calls_pending", "data": {"pending_tool_calls": PENDING}}))
        paused_agent._pending_continuation = {"messages": [], "tools_dict": {}, "pending_tool_calls": PENDING}
        with flask_app.app_context():
            _stream(_resource(), paused_agent)
        assert saved["agent_config"]["decisions"]["entries"][0]["round"] == 0

        resumed_agent = _agent()
        resumed_agent.gen_continuation.side_effect = _deciding("rag_rerank", {"answer": "done"})
        stored_state = _pending_state({"decisions": json.loads(json.dumps(saved["agent_config"]["decisions"]))})
        agent, processor = resume(stored_state, resumed_agent)
        resource = _resource()
        with flask_app.app_context():
            _stream(resource, agent, question="", _continuation={
                "messages": [], "tools_dict": {}, "pending_tool_calls": PENDING, "tool_actions": [],
                "reserved_message_id": "m1", "request_id": processor.request_id,
            })

        stored = _finalized(resource)["decisions"]
        assert [(e["feature"], e["round"]) for e in stored["entries"]] == [("injection_input", 0), ("rag_rerank", 1)]
