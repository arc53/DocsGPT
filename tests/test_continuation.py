"""Tests for the continuation infrastructure.

Covers ContinuationService, ToolExecutor.check_pause, handler pause
signaling, BaseAgent.gen_continuation, and request validation.
"""

import uuid
from unittest.mock import Mock, MagicMock

import pytest

from application.agents.tool_executor import ToolExecutor
from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


# ---------------------------------------------------------------------------
# In-memory MongoDB collection mock (no mongomock / bson dependency)
# ---------------------------------------------------------------------------


class _InMemoryCollection:
    """Minimal dict-backed collection supporting find_one, replace_one, delete_one."""

    def __init__(self):
        self._docs = []

    def _matches(self, doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    def find_one(self, query):
        for doc in self._docs:
            if self._matches(doc, query):
                import copy
                return copy.deepcopy(doc)
        return None

    def replace_one(self, query, replacement, upsert=False):
        result = MagicMock()
        for i, doc in enumerate(self._docs):
            if self._matches(doc, query):
                self._docs[i] = dict(replacement)
                if "_id" not in self._docs[i]:
                    self._docs[i]["_id"] = str(uuid.uuid4())
                result.upserted_id = None
                return result
        if upsert:
            new_doc = dict(replacement)
            new_doc["_id"] = str(uuid.uuid4())
            self._docs.append(new_doc)
            result.upserted_id = new_doc["_id"]
        else:
            result.upserted_id = None
        return result

    def delete_one(self, query):
        result = MagicMock()
        for i, doc in enumerate(self._docs):
            if self._matches(doc, query):
                self._docs.pop(i)
                result.deleted_count = 1
                return result
        result.deleted_count = 0
        return result

    def create_index(self, *args, **kwargs):
        pass  # no-op


class _InMemoryDB:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _InMemoryCollection()
        return self._collections[name]


@pytest.fixture
def mock_mongo_continuation(monkeypatch):
    """Provide an in-memory MongoDB for ContinuationService (no bson/mongomock)."""
    db = _InMemoryDB()
    mock_client = {_get_mongo_db_name(): db}

    def _get_client():
        return mock_client

    monkeypatch.setattr(
        "application.api.answer.services.continuation_service.MongoDB.get_client",
        _get_client,
    )
    monkeypatch.setattr(
        "application.storage.db.dual_write.dual_write",
        lambda repo_cls, fn: None,
    )
    return db


def _get_mongo_db_name():
    from application.core.settings import settings
    return settings.MONGO_DB_NAME


# ---------------------------------------------------------------------------
# ContinuationService
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skip(reason="needs PG fixture rewrite — tracked as part of post-cutover test cleanup")
class TestContinuationService:

    def test_save_and_load(self, mock_mongo_continuation):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        svc = ContinuationService()
        svc.save_state(
            conversation_id="conv-1",
            user="alice",
            messages=[{"role": "user", "content": "hi"}],
            pending_tool_calls=[{"call_id": "c1", "pause_type": "awaiting_approval"}],
            tools_dict={"0": {"name": "test_tool"}},
            tool_schemas=[{"type": "function", "function": {"name": "act_0"}}],
            agent_config={"model_id": "gpt-4"},
        )

        state = svc.load_state("conv-1", "alice")
        assert state is not None
        assert state["conversation_id"] == "conv-1"
        assert state["user"] == "alice"
        assert len(state["messages"]) == 1
        assert len(state["pending_tool_calls"]) == 1
        assert state["agent_config"]["model_id"] == "gpt-4"

    def test_load_returns_none_when_missing(self, mock_mongo_continuation):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        svc = ContinuationService()
        assert svc.load_state("nonexistent", "alice") is None

    def test_delete_state(self, mock_mongo_continuation):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        svc = ContinuationService()
        svc.save_state(
            conversation_id="conv-2",
            user="bob",
            messages=[],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )
        assert svc.delete_state("conv-2", "bob") is True
        assert svc.load_state("conv-2", "bob") is None

    def test_delete_nonexistent(self, mock_mongo_continuation):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        svc = ContinuationService()
        assert svc.delete_state("nope", "nope") is False

    def test_upsert_replaces_existing(self, mock_mongo_continuation):
        from application.api.answer.services.continuation_service import (
            ContinuationService,
        )

        svc = ContinuationService()
        svc.save_state(
            conversation_id="conv-3",
            user="carol",
            messages=[{"role": "user", "content": "v1"}],
            pending_tool_calls=[],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )
        svc.save_state(
            conversation_id="conv-3",
            user="carol",
            messages=[{"role": "user", "content": "v2"}],
            pending_tool_calls=[{"call_id": "c2"}],
            tools_dict={},
            tool_schemas=[],
            agent_config={},
        )
        state = svc.load_state("conv-3", "carol")
        assert state["messages"][0]["content"] == "v2"
        assert len(state["pending_tool_calls"]) == 1


# ---------------------------------------------------------------------------
# ToolExecutor.check_pause
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPause:

    def _make_call(self, name="action_0", call_id="c1", arguments="{}"):
        call = Mock()
        call.name = name
        call.id = call_id
        call.arguments = arguments
        call.thought_signature = None
        return call

    def test_returns_none_for_normal_tool(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "brave",
                "actions": [
                    {"name": "search", "active": True, "parameters": {}},
                ],
            }
        }
        call = self._make_call(name="search_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is None

    def test_returns_pause_for_client_side_tool(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "get_weather",
                "client_side": True,
                "actions": [
                    {"name": "get_weather", "active": True, "parameters": {}},
                ],
            }
        }
        call = self._make_call(name="get_weather_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "requires_client_execution"
        assert result["call_id"] == "c1"
        assert result["tool_id"] == "0"

    def test_returns_pause_for_approval_required(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "telegram",
                "actions": [
                    {
                        "name": "send_msg",
                        "active": True,
                        "require_approval": True,
                        "parameters": {},
                    },
                ],
            }
        }
        call = self._make_call(name="send_msg_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "awaiting_approval"

    def test_returns_none_when_parse_fails(self):
        executor = ToolExecutor()
        call = self._make_call(name="bad_name_no_id", arguments="not json")
        # Bad arguments will cause parse error -> None
        result = executor.check_pause({}, call, "OpenAILLM")
        assert result is None

    def test_returns_none_when_tool_not_in_dict(self):
        executor = ToolExecutor()
        call = self._make_call(name="action_99")
        result = executor.check_pause({"0": {"name": "t"}}, call, "OpenAILLM")
        assert result is None

    def test_api_tool_approval(self):
        executor = ToolExecutor()
        tools_dict = {
            "0": {
                "name": "api_tool",
                "config": {
                    "actions": {
                        "delete_user": {
                            "name": "delete_user",
                            "require_approval": True,
                            "url": "http://example.com",
                            "method": "DELETE",
                            "active": True,
                        }
                    }
                },
            }
        }
        call = self._make_call(name="delete_user_0")
        result = executor.check_pause(tools_dict, call, "OpenAILLM")
        assert result is not None
        assert result["pause_type"] == "awaiting_approval"


# ---------------------------------------------------------------------------
# Handler pause signaling (handle_tool_calls returns pending_actions)
# ---------------------------------------------------------------------------


class ConcreteHandler(LLMHandler):
    """Minimal concrete handler for testing."""

    def parse_response(self, response):
        return LLMResponse(
            content=str(response), tool_calls=[], finish_reason="stop",
            raw_response=response,
        )

    def create_tool_message(self, tool_call, result):
        return {
            "role": "tool",
            "content": [
                {
                    "function_response": {
                        "name": tool_call.name,
                        "response": {"result": result},
                        "call_id": tool_call.id,
                    }
                }
            ],
        }

    def _iterate_stream(self, response):
        for chunk in response:
            yield chunk


@pytest.mark.unit
class TestHandlerPauseSignaling:

    def _make_agent(self):
        agent = Mock()
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)

        def fake_execute(tools_dict, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("tool result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)
        return agent

    def test_no_pause_returns_none_pending(self):
        handler = ConcreteHandler()
        agent = self._make_agent()
        call = ToolCall(id="c1", name="action_0", arguments="{}")

        gen = handler.handle_tool_calls(agent, [call], {"0": {"name": "t"}}, [])
        events = []
        messages = None
        pending = "NOT_SET"
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            messages, pending = e.value

        assert pending is None
        assert messages is not None

    def test_pause_returns_pending_actions(self):
        handler = ConcreteHandler()
        agent = self._make_agent()
        agent.tool_executor.check_pause = Mock(return_value={
            "call_id": "c1",
            "name": "send_msg_0",
            "tool_name": "telegram",
            "tool_id": "0",
            "action_name": "send_msg",
            "arguments": {"text": "hello"},
            "pause_type": "awaiting_approval",
            "thought_signature": None,
        })

        call = ToolCall(id="c1", name="send_msg_0", arguments='{"text": "hello"}')
        gen = handler.handle_tool_calls(
            agent, [call], {"0": {"name": "telegram"}}, []
        )

        events = []
        pending = None
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            messages, pending = e.value

        assert pending is not None
        assert len(pending) == 1
        assert pending[0]["pause_type"] == "awaiting_approval"

        # Should have yielded a tool_call event with awaiting_approval status
        pause_events = [
            e for e in events
            if e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "awaiting_approval"
        ]
        assert len(pause_events) == 1

    def test_mixed_execute_and_pause(self):
        """One tool executes, another needs approval."""
        handler = ConcreteHandler()
        agent = self._make_agent()

        call_count = {"n": 0}

        def selective_pause(tools_dict, call, llm_class):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return {
                    "call_id": "c2",
                    "name": "danger_0",
                    "tool_name": "danger",
                    "tool_id": "0",
                    "action_name": "danger",
                    "arguments": {},
                    "pause_type": "awaiting_approval",
                    "thought_signature": None,
                }
            return None

        agent.tool_executor.check_pause = Mock(side_effect=selective_pause)

        calls = [
            ToolCall(id="c1", name="safe_0", arguments="{}"),
            ToolCall(id="c2", name="danger_0", arguments="{}"),
        ]
        gen = handler.handle_tool_calls(
            agent, calls, {"0": {"name": "multi"}}, []
        )

        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            messages, pending = e.value

        # First tool was executed normally
        assert agent._execute_tool_action.call_count == 1
        # Second tool is pending
        assert pending is not None
        assert len(pending) == 1
        assert pending[0]["call_id"] == "c2"


# ---------------------------------------------------------------------------
# handle_streaming yields tool_calls_pending
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStreamingPause:

    def test_streaming_yields_tool_calls_pending(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.llm = Mock()
        agent.model_id = "test"
        agent.tools = []
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"

        pause_info = {
            "call_id": "c1",
            "name": "fn_0",
            "tool_name": "test",
            "tool_id": "0",
            "action_name": "fn",
            "arguments": {},
            "pause_type": "awaiting_approval",
            "thought_signature": None,
        }
        agent.tool_executor.check_pause = Mock(return_value=pause_info)

        chunk = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="fn_0", arguments="{}", index=0)],
            finish_reason="tool_calls",
            raw_response={},
        )
        handler.parse_response = lambda c: c

        def fake_iterate(response):
            yield from response

        handler._iterate_stream = fake_iterate

        gen = handler.handle_streaming(agent, [chunk], {"0": {"name": "t"}}, [])
        events = list(gen)

        # Should contain a tool_calls_pending event
        pending_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "tool_calls_pending"
        ]
        assert len(pending_events) == 1
        assert len(pending_events[0]["data"]["pending_tool_calls"]) == 1

        # Agent should have _pending_continuation set
        assert hasattr(agent, "_pending_continuation")


# ---------------------------------------------------------------------------
# BaseAgent.gen_continuation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenContinuation:

    def test_approved_tool_executes(self):
        """When a tool action is approved, the tool is executed."""
        from application.agents.classic_agent import ClassicAgent

        mock_llm = Mock()
        mock_llm._supports_tools = True
        mock_llm.gen_stream = Mock(return_value=iter(["Final answer"]))
        mock_llm._supports_structured_output = Mock(return_value=False)
        mock_llm.__class__.__name__ = "MockLLM"

        mock_handler = Mock()
        mock_handler.process_message_flow = Mock(return_value=iter([]))
        mock_handler.create_tool_message = Mock(
            return_value={"role": "tool", "content": [{"function_response": {
                "name": "act_0", "response": {"result": "done"}, "call_id": "c1"
            }}]}
        )

        mock_executor = Mock()
        mock_executor.tool_calls = []
        mock_executor.prepare_tools_for_llm = Mock(return_value=[])
        mock_executor.get_truncated_tool_calls = Mock(return_value=[])

        def fake_execute(tools_dict, call, llm_class):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("result_data", "c1")

        mock_executor.execute = Mock(side_effect=fake_execute)

        agent = ClassicAgent(
            endpoint="stream",
            llm_name="openai",
            model_id="gpt-4",
            api_key="test",
            llm=mock_llm,
            llm_handler=mock_handler,
            tool_executor=mock_executor,
        )

        messages = [{"role": "system", "content": "You are helpful."}]
        tools_dict = {"0": {"name": "test_tool"}}
        pending = [
            {
                "call_id": "c1",
                "name": "act_0",
                "tool_name": "test_tool",
                "tool_id": "0",
                "action_name": "act",
                "arguments": {"q": "test"},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            }
        ]
        tool_actions = [{"call_id": "c1", "decision": "approved"}]

        list(agent.gen_continuation(messages, tools_dict, pending, tool_actions))

        # Tool should have been executed
        assert mock_executor.execute.called

    def test_denied_tool_sends_denial(self):
        """When a tool action is denied, a denial message is added."""
        from application.agents.classic_agent import ClassicAgent

        mock_llm = Mock()
        mock_llm._supports_tools = True
        mock_llm.gen_stream = Mock(return_value=iter(["Answer"]))
        mock_llm._supports_structured_output = Mock(return_value=False)
        mock_llm.__class__.__name__ = "MockLLM"

        mock_handler = Mock()
        mock_handler.process_message_flow = Mock(return_value=iter([]))
        mock_handler.create_tool_message = Mock(
            return_value={"role": "tool", "content": "denied"}
        )

        mock_executor = Mock()
        mock_executor.tool_calls = []
        mock_executor.prepare_tools_for_llm = Mock(return_value=[])
        mock_executor.get_truncated_tool_calls = Mock(return_value=[])

        agent = ClassicAgent(
            endpoint="stream",
            llm_name="openai",
            model_id="gpt-4",
            api_key="test",
            llm=mock_llm,
            llm_handler=mock_handler,
            tool_executor=mock_executor,
        )

        messages = [{"role": "system", "content": "test"}]
        pending = [
            {
                "call_id": "c1",
                "name": "danger_0",
                "tool_name": "danger",
                "tool_id": "0",
                "action_name": "danger",
                "arguments": {},
                "pause_type": "awaiting_approval",
                "thought_signature": None,
            }
        ]
        tool_actions = [
            {"call_id": "c1", "decision": "denied", "comment": "too risky"}
        ]

        events = list(
            agent.gen_continuation(messages, {"0": {"name": "danger"}}, pending, tool_actions)
        )

        # Should have a denied tool_call event
        denied = [
            e for e in events
            if isinstance(e, dict)
            and e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "denied"
        ]
        assert len(denied) == 1

        # create_tool_message should have been called with denial text
        denial_arg = mock_handler.create_tool_message.call_args[0][1]
        assert "denied" in denial_arg.lower()
        assert "too risky" in denial_arg

    def test_client_result_appended(self):
        """Client-provided tool result is added to messages."""
        from application.agents.classic_agent import ClassicAgent

        mock_llm = Mock()
        mock_llm._supports_tools = True
        mock_llm.gen_stream = Mock(return_value=iter(["Done"]))
        mock_llm._supports_structured_output = Mock(return_value=False)
        mock_llm.__class__.__name__ = "MockLLM"

        mock_handler = Mock()
        mock_handler.process_message_flow = Mock(return_value=iter([]))
        mock_handler.create_tool_message = Mock(
            return_value={"role": "tool", "content": "client result"}
        )

        mock_executor = Mock()
        mock_executor.tool_calls = []
        mock_executor.prepare_tools_for_llm = Mock(return_value=[])
        mock_executor.get_truncated_tool_calls = Mock(return_value=[])

        agent = ClassicAgent(
            endpoint="stream",
            llm_name="openai",
            model_id="gpt-4",
            api_key="test",
            llm=mock_llm,
            llm_handler=mock_handler,
            tool_executor=mock_executor,
        )

        messages = [{"role": "system", "content": "test"}]
        pending = [
            {
                "call_id": "c1",
                "name": "weather_0",
                "tool_name": "weather",
                "tool_id": "0",
                "action_name": "weather",
                "arguments": {"city": "SF"},
                "pause_type": "requires_client_execution",
                "thought_signature": None,
            }
        ]
        tool_actions = [{"call_id": "c1", "result": {"temp": "72F"}}]

        events = list(
            agent.gen_continuation(messages, {"0": {"name": "weather"}}, pending, tool_actions)
        )

        # create_tool_message was called with the client result
        result_arg = mock_handler.create_tool_message.call_args[0][1]
        assert "72F" in result_arg

        # Should have a completed tool_call event
        completed = [
            e for e in events
            if isinstance(e, dict)
            and e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "completed"
        ]
        assert len(completed) == 1


# ---------------------------------------------------------------------------
# validate_request
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateRequest:

    @pytest.fixture(autouse=True)
    def _app_context(self):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            yield

    def test_continuation_request_without_question(self):
        from application.api.answer.routes.base import BaseAnswerResource

        base = BaseAnswerResource()
        data = {
            "conversation_id": "conv-1",
            "tool_actions": [{"call_id": "c1", "decision": "approved"}],
        }
        result = base.validate_request(data)
        assert result is None  # Valid

    def test_continuation_request_missing_conversation_id(self):
        from application.api.answer.routes.base import BaseAnswerResource

        base = BaseAnswerResource()
        data = {
            "tool_actions": [{"call_id": "c1", "decision": "approved"}],
        }
        result = base.validate_request(data)
        assert result is not None  # Error — missing conversation_id

    def test_normal_request_still_requires_question(self):
        from application.api.answer.routes.base import BaseAnswerResource

        base = BaseAnswerResource()
        data = {"conversation_id": "conv-1"}
        result = base.validate_request(data)
        assert result is not None  # Error — missing question


# ---------------------------------------------------------------------------
# Resume durability: mark_resuming on resume, delete only on success
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResumeMarkResuming:
    """Resumed runs must mark state ``resuming`` instead of deleting it
    eagerly; the row stays in PG so a crashed resume can be retried."""

    def test_resume_calls_mark_resuming_not_delete(self, monkeypatch):
        """``resume_from_tool_actions`` flips the row to 'resuming' and
        does not delete it before the run finishes."""
        from application.api.answer.services import (
            continuation_service as cont_mod,
        )
        from application.api.answer.services import stream_processor as sp_mod
        from application.llm import llm_creator as llm_creator_mod
        from application.llm.handlers import handler_creator as handler_mod

        cont_service = MagicMock()
        cont_service.load_state.return_value = {
            "messages": [],
            "pending_tool_calls": [],
            "tools_dict": {},
            "tool_schemas": [],
            "agent_config": {
                "model_id": "m1",
                "model_user_id": None,
                "llm_name": "openai",
                "api_key": "k",
                "user_api_key": None,
                "agent_id": None,
                "agent_type": "ClassicAgent",
                "prompt": "",
                "json_schema": None,
                "retriever_config": None,
            },
            "client_tools": None,
        }
        cont_service.mark_resuming.return_value = True

        monkeypatch.setattr(
            cont_mod, "ContinuationService", lambda: cont_service
        )
        monkeypatch.setattr(
            llm_creator_mod.LLMCreator,
            "create_llm",
            lambda *a, **kw: MagicMock(),
        )
        monkeypatch.setattr(
            handler_mod.LLMHandlerCreator,
            "create_handler",
            lambda *a, **kw: MagicMock(),
        )
        from application.agents import agent_creator as ac_mod
        from application.agents import tool_executor as te_mod

        monkeypatch.setattr(
            te_mod, "ToolExecutor", lambda **kw: MagicMock(client_tools=None)
        )
        monkeypatch.setattr(
            ac_mod.AgentCreator, "create_agent", lambda *a, **kw: MagicMock()
        )

        sp = sp_mod.StreamProcessor.__new__(sp_mod.StreamProcessor)
        sp.data = {}
        sp.decoded_token = {"sub": "alice"}
        sp.initial_user_id = "alice"
        sp.conversation_id = "00000000-0000-0000-0000-000000000001"
        sp.agent_config = {}

        sp.resume_from_tool_actions(
            tool_actions=[],
            conversation_id="00000000-0000-0000-0000-000000000001",
        )

        cont_service.mark_resuming.assert_called_once_with(
            "00000000-0000-0000-0000-000000000001", "alice"
        )
        cont_service.delete_state.assert_not_called()

    def test_resume_extracts_reserved_message_id_from_agent_config(
        self, monkeypatch
    ):
        """The WAL placeholder id stashed in ``agent_config`` at pause time
        must be hoisted onto the processor so the resumed ``complete_stream``
        finalises the same row instead of stranding it."""
        from application.api.answer.services import (
            continuation_service as cont_mod,
        )
        from application.api.answer.services import stream_processor as sp_mod
        from application.llm import llm_creator as llm_creator_mod
        from application.llm.handlers import handler_creator as handler_mod

        reserved_id = "22222222-2222-2222-2222-222222222222"

        cont_service = MagicMock()
        cont_service.load_state.return_value = {
            "messages": [],
            "pending_tool_calls": [],
            "tools_dict": {},
            "tool_schemas": [],
            "agent_config": {
                "model_id": "m1",
                "model_user_id": None,
                "llm_name": "openai",
                "api_key": "k",
                "user_api_key": None,
                "agent_id": None,
                "agent_type": "ClassicAgent",
                "prompt": "",
                "json_schema": None,
                "retriever_config": None,
                "reserved_message_id": reserved_id,
            },
            "client_tools": None,
        }
        cont_service.mark_resuming.return_value = True
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        monkeypatch.setattr(
            llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock(),
        )
        monkeypatch.setattr(
            handler_mod.LLMHandlerCreator, "create_handler",
            lambda *a, **kw: MagicMock(),
        )
        from application.agents import agent_creator as ac_mod
        from application.agents import tool_executor as te_mod

        monkeypatch.setattr(
            te_mod, "ToolExecutor", lambda **kw: MagicMock(client_tools=None)
        )
        monkeypatch.setattr(
            ac_mod.AgentCreator, "create_agent", lambda *a, **kw: MagicMock()
        )

        sp = sp_mod.StreamProcessor.__new__(sp_mod.StreamProcessor)
        sp.data = {}
        sp.decoded_token = {"sub": "alice"}
        sp.initial_user_id = "alice"
        sp.conversation_id = "00000000-0000-0000-0000-000000000001"
        sp.agent_config = {}
        sp.reserved_message_id = None

        sp.resume_from_tool_actions(
            tool_actions=[],
            conversation_id="00000000-0000-0000-0000-000000000001",
        )

        assert sp.reserved_message_id == reserved_id


@pytest.mark.unit
class TestContinuationServiceMarkResuming:
    """``ContinuationService.mark_resuming`` is the thin wrapper used by
    the resume path; it should flip the repository row in place."""

    def test_mark_resuming_flips_pending_row(self, pg_engine, monkeypatch):
        from contextlib import contextmanager

        from application.api.answer.services import (
            continuation_service as cont_mod,
        )
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )
        from application.storage.db.repositories.pending_tool_state import (
            PendingToolStateRepository,
        )

        with pg_engine.begin() as conn:
            conv = ConversationsRepository(conn).create("alice", "c")
            PendingToolStateRepository(conn).save_state(
                conv["id"],
                "alice",
                messages=[],
                pending_tool_calls=[],
                tools_dict={},
                tool_schemas=[],
                agent_config={},
            )

        @contextmanager
        def _session():
            with pg_engine.begin() as conn:
                yield conn

        @contextmanager
        def _readonly():
            with pg_engine.connect() as conn:
                yield conn

        monkeypatch.setattr(cont_mod, "db_session", _session)
        monkeypatch.setattr(cont_mod, "db_readonly", _readonly)

        svc = cont_mod.ContinuationService()
        flipped = svc.mark_resuming(conv["id"], "alice")
        assert flipped is True

        with pg_engine.connect() as conn:
            row = PendingToolStateRepository(conn).load_state(
                conv["id"], "alice"
            )
        assert row["status"] == "resuming"
        assert row["resumed_at"] is not None

    def test_mark_resuming_returns_false_for_unknown_conv(
        self, pg_engine, monkeypatch
    ):
        from contextlib import contextmanager

        from application.api.answer.services import (
            continuation_service as cont_mod,
        )

        @contextmanager
        def _session():
            with pg_engine.begin() as conn:
                yield conn

        @contextmanager
        def _readonly():
            with pg_engine.connect() as conn:
                yield conn

        monkeypatch.setattr(cont_mod, "db_session", _session)
        monkeypatch.setattr(cont_mod, "db_readonly", _readonly)

        svc = cont_mod.ContinuationService()
        # Not a UUID and no legacy row exists.
        assert svc.mark_resuming("not-a-uuid", "alice") is False
