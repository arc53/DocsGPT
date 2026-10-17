"""A small window must not turn the tool loop into an endless re-read.

E2E (8k and 3k windows): every ``attachments_read`` round crossed the
compression threshold; the compression could not shrink the turn ("did not
reduce"), the context was pruned back to the question, the model lost the
reads and asked for them again, and the turn ran for 21+ minutes.
"""

from types import SimpleNamespace
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.llm.handlers.base import LLMHandler, LLMResponse, ToolCall

pytestmark = pytest.mark.unit


class _ScriptHandler(LLMHandler):
    def parse_response(self, response: Any) -> LLMResponse:
        return response

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "tool_call_id": tool_call.id, "content": str(result)}

    def _iterate_stream(self, response: Any) -> Generator:
        yield from response


def _reads(n, start=0):
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id=f"c{start + i}", name="attachments_read", arguments={"ref": f"F{i + 1}"}, index=None)
            for i in range(n)
        ],
        finish_reason="tool_calls",
        raw_response=None,
    )


def _stop():
    return LLMResponse(content="", tool_calls=[], finish_reason="stop", raw_response=None)


class _ReadingLLM:
    """A model that asks for the files again whenever tools are offered."""

    def __init__(self):
        self.model_id = "small"
        self._responding_provider = None
        self._fallback_llm = None
        self._stream_reached_finish = False
        self.tools_seen = []

    def gen_stream(self, model, messages, tools=None, **kwargs):
        self.tools_seen.append(tools)
        if tools:
            return iter([_reads(3, start=len(self.tools_seen) * 10)])
        return iter(["honest answer from what was read", _stop()])


def _agent(llm, limit_after=2):
    executed = []

    def _execute(tools_dict, call):
        if False:  # pragma: no cover
            yield None
        executed.append(call.name)
        return ("x" * 200, call.id)

    agent = SimpleNamespace(
        llm=llm,
        model_id="small",
        tools=[{"type": "function", "function": {"name": "attachments_read"}}],
        tool_executor=SimpleNamespace(
            check_pause=lambda tools_dict, call, llm_class: None,
            context_room_tokens=None,
            context_epoch=0,
        ),
        _execute_tool_action=_execute,
        context_limit_reached=False,
        executed=executed,
    )
    # Over the threshold once a couple of tool results are in.
    agent._check_context_limit = lambda messages: sum(1 for m in messages if m.get("role") == "tool") >= limit_after
    agent._context_room_tokens = lambda messages: 5_000
    return agent


def _drain(gen):
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as e:
            return events, e.value


class TestCompressionThatCannotReduce:
    def test_the_loop_stops_and_answers_after_one_failed_compression(self):
        llm = _ReadingLLM()
        agent = _agent(llm)
        handler = _ScriptHandler()
        attempts = []

        def _cannot_reduce(a, messages):
            attempts.append(len(messages))
            a._compression_exhausted = True
            return False, None

        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "summarise F1-F3"}]
        with patch("docsgpt.core.settings.settings.ENABLE_CONVERSATION_COMPRESSION", True), patch.object(
            handler, "_perform_mid_execution_compression", side_effect=_cannot_reduce
        ):
            events, _ = _drain(handler.handle_streaming(agent, iter([_reads(3)]), {}, messages))

        answer = "".join(e for e in events if isinstance(e, str))
        assert answer == "honest answer from what was read"
        assert len(attempts) == 1, "a compression that cannot reduce is not retried every round"
        assert llm.tools_seen == [None], "the next call wraps up without tools"
        skipped = [e for e in events if isinstance(e, dict) and e.get("data", {}).get("status") == "skipped"]
        assert len(skipped) == 1

    def test_an_exhausted_turn_never_calls_compression_again(self):
        llm = _ReadingLLM()
        agent = _agent(llm, limit_after=0)
        agent._compression_exhausted = True
        handler = _ScriptHandler()
        with patch("docsgpt.core.settings.settings.ENABLE_CONVERSATION_COMPRESSION", True), patch.object(
            handler, "_perform_mid_execution_compression"
        ) as compress:
            _drain(handler.handle_tool_calls(agent, _reads(2).tool_calls, {}, [{"role": "system", "content": "s"}]))
        compress.assert_not_called()
        assert agent.context_limit_reached is True
        assert agent.executed == []


class TestRoomForEachRead:
    def test_the_executor_is_told_the_room_before_each_call(self):
        llm = _ReadingLLM()
        agent = _agent(llm, limit_after=99)
        rooms = iter([4_000, 2_500])
        agent._context_room_tokens = lambda messages: next(rooms)
        seen = []

        def _execute(tools_dict, call):
            if False:  # pragma: no cover
                yield None
            seen.append(agent.tool_executor.context_room_tokens)
            return ("ok", call.id)

        agent._execute_tool_action = _execute
        _drain(_ScriptHandler().handle_tool_calls(agent, _reads(2).tool_calls, {}, [{"role": "system", "content": "s"}]))
        assert seen == [4_000, 2_500]

    def test_a_successful_compression_starts_a_new_read_epoch(self):
        llm = _ReadingLLM()
        agent = _agent(llm, limit_after=0)
        handler = _ScriptHandler()
        with patch("docsgpt.core.settings.settings.ENABLE_CONVERSATION_COMPRESSION", True), patch.object(
            handler,
            "_perform_mid_execution_compression",
            return_value=(True, [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]),
        ):
            agent._check_context_limit = MagicMock(side_effect=[True, False])
            _drain(handler.handle_tool_calls(agent, _reads(1).tool_calls, {}, [{"role": "system", "content": "s"}]))
        assert agent.tool_executor.context_epoch == 1
