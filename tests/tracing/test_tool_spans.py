"""Tool calls become ``execute_tool`` spans: executed, paused, denied, skipped."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from docsgpt import tracing
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.core.settings import settings
from docsgpt.llm.handlers.base import LLMHandler, ToolCall


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", True)


@pytest.fixture()
def trace():
    t = tracing.start_trace(source="stream", capture_otel_context=False)
    with tracing.activate(t):
        yield t


def _executor_with(inner):
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.tool_calls = []
    executor._execute = lambda tools_dict, call, llm_class_name: inner(executor, call)
    return executor


def _drain(gen):
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as stop:
            return events, stop.value


class TestExecute:
    def test_completed_call(self, trace):
        def inner(executor, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            executor.tool_calls.append(
                {
                    "tool_name": "brave",
                    "action_name": "search",
                    "arguments": {"q": "x", "api_key": "k"},
                    "result": "3 results",
                    "status": "completed",
                }
            )
            return "3 results", call.id

        executor = _executor_with(inner)
        call = ToolCall(id="c1", name="search_1", arguments="{}")
        events, outcome = _drain(executor.execute({}, call, "OpenAILLM"))
        assert outcome == ("3 results", "c1")
        assert len(events) == 1
        (span,) = trace.spans
        assert span.kind == tracing.KIND_TOOL
        assert span.name == "execute_tool search_1"
        assert span.status == "ok"
        assert span.attributes["gen_ai.tool.call.id"] == "c1"
        assert span.attributes["docsgpt.tool"] == "brave"
        assert span.previews["arguments"]["api_key"] == "[REDACTED]"
        assert span.previews["result"] == "3 results"

    def test_in_band_error(self, trace):
        def inner(executor, call):
            executor.tool_calls.append(
                {"tool_name": "unknown", "result": "no such tool", "status": "error"}
            )
            return "no such tool", call.id
            yield  # pragma: no cover

        executor = _executor_with(inner)
        _drain(executor.execute({}, ToolCall(id="c", name="x", arguments="{}"), "L"))
        span = trace.spans[0]
        assert span.status == "error"
        assert span.error == "no such tool"

    def test_raised_error(self, trace):
        def inner(executor, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            raise RuntimeError("api down")

        executor = _executor_with(inner)
        with pytest.raises(RuntimeError):
            _drain(executor.execute({}, ToolCall(id="c", name="x", arguments="{}"), "L"))
        assert trace.spans[0].status == "error"
        assert trace.spans[0].attributes["error.type"] == "RuntimeError"

    def test_nested_retrieval_parents_to_tool(self, trace):
        def inner(executor, call):
            with tracing.span(tracing.KIND_RETRIEVAL, "retrieval"):
                pass
            executor.tool_calls.append({"status": "completed"})
            return "", call.id
            yield  # pragma: no cover

        executor = _executor_with(inner)
        _drain(executor.execute({}, ToolCall(id="c", name="internal_search", arguments="{}"), "L"))
        tool, retrieval = trace.spans
        assert retrieval.parent_id == tool.id


class _Handler(LLMHandler):
    def parse_response(self, response):  # pragma: no cover - unused
        raise NotImplementedError

    def create_tool_message(self, tool_call, result):
        return {"role": "tool", "content": str(result)}

    def _iterate_stream(self, response):  # pragma: no cover - unused
        return iter(())


class TestPausedCalls:
    def _agent(self, pause):
        agent = Mock()
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=pause)
        return agent

    def test_awaiting_approval_is_pending(self, trace):
        agent = self._agent(
            {
                "call_id": "c1",
                "name": "send_0",
                "tool_name": "telegram",
                "tool_id": "0",
                "action_name": "send",
                "arguments": {"text": "hi"},
                "pause_type": "awaiting_approval",
            }
        )
        call = ToolCall(id="c1", name="send_0", arguments='{"text": "hi"}')
        _drain(_Handler().handle_tool_calls(agent, [call], {"0": {"name": "telegram"}}, []))
        (span,) = trace.spans
        assert span.status == "pending"
        assert span.attributes["docsgpt.tool_status"] == "awaiting_approval"

    def test_headless_denial_is_denied(self, trace):
        agent = self._agent(
            {
                "call_id": "c1",
                "name": "send_0",
                "tool_name": "telegram",
                "tool_id": "0",
                "action_name": "send",
                "arguments": {},
                "pause_type": "headless_denied",
                "deny_reason": "not allowed",
            }
        )
        agent.tool_executor.message_id = None
        agent.tool_executor.user = "u"
        agent.tool_executor.agent_id = None
        call = ToolCall(id="c1", name="send_0", arguments="{}")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("docsgpt.agents.tool_executor._record_proposed", lambda *a, **k: False)
            _drain(_Handler().handle_tool_calls(agent, [call], {"0": {"name": "telegram"}}, []))
        (span,) = trace.spans
        assert span.status == "denied"
        assert span.error == "not allowed"


class TestContinuation:
    def _agent(self):
        from docsgpt.agents.classic_agent import ClassicAgent

        llm = Mock()
        llm._supports_tools = True
        llm.gen_stream = Mock(return_value=iter(["Answer"]))
        llm._supports_structured_output = Mock(return_value=False)
        handler = Mock()
        handler.process_message_flow = Mock(return_value=iter([]))
        handler.create_tool_message = Mock(return_value={"role": "tool", "content": "x"})
        executor = Mock()
        executor.tool_calls = []
        executor.prepare_tools_for_llm = Mock(return_value=[])
        executor.get_truncated_tool_calls = Mock(return_value=[])
        return ClassicAgent(
            endpoint="stream",
            llm_name="openai",
            model_id="gpt-4",
            api_key="test",
            llm=llm,
            llm_handler=handler,
            tool_executor=executor,
        )

    def _pending(self):
        return [
            {
                "call_id": "c1",
                "name": "danger_0",
                "tool_name": "danger",
                "tool_id": "0",
                "action_name": "danger",
                "arguments": {},
                "pause_type": "awaiting_approval",
            }
        ]

    def test_continuation_opens_agent_span_with_denied_tool(self, trace):
        agent = self._agent()
        list(
            agent.gen_continuation(
                [{"role": "system", "content": "s"}],
                {"0": {"name": "danger"}},
                self._pending(),
                [{"call_id": "c1", "decision": "denied", "comment": "too risky"}],
            )
        )
        agent_span = trace.spans[0]
        tool_span = trace.spans[1]
        assert agent_span.kind == tracing.KIND_AGENT
        assert agent_span.attributes["docsgpt.continuation"] is True
        assert agent_span.status == "ok"
        assert tool_span.parent_id == agent_span.id
        assert tool_span.status == "denied"
        assert tool_span.error == "too risky"

    def test_client_result_is_recorded(self, trace):
        agent = self._agent()
        list(
            agent.gen_continuation(
                [{"role": "system", "content": "s"}],
                {"0": {"name": "danger"}},
                self._pending(),
                [{"call_id": "c1", "result": {"ok": True}}],
            )
        )
        tool_span = trace.spans[1]
        assert tool_span.status == "ok"
        assert tool_span.attributes["docsgpt.client_executed"] is True
