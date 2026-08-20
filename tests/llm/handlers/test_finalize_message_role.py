"""#49 regression: cap/context-limit "wrap up" instructions must be USER turns.

Prod 2026-08-18: ``@cf/qwen/qwen3.8-27b`` (vLLM-style chat template) rejects
any request whose system message is not at position 0 — 400 "System message
must be at the beginning." The tool-loop-cap and context-limit paths appended
their finalize instruction as a TRAILING system message, so the one turn whose
job was to wrap up gracefully killed the primary model and the user got a
fallback answer instead. Live-probed 2026-08-20: qwen accepts the identical
instruction as a ``user`` turn, and every other served model accepts both
forms — so the instruction rides as a user turn.

These tests drive the real handler flows (streaming cap, streaming
context-limit, non-streaming cap) with scripted LLMResponse objects and pin,
on the messages array actually SENT to the provider for the finalize round
(``handle_tool_calls`` works on a copy, so the caller's list is not mutated):
the injected instruction is a ``user`` message, no ``system`` message ever
appears past position 0, and the finalize round still sends ``tools=None``.
"""

from types import SimpleNamespace
from typing import Any, Dict, Generator

from application.llm.handlers.base import (
    _FINALIZE_INSTRUCTION,
    MAX_TOOL_ITERATIONS,
    LLMHandler,
    LLMResponse,
    ToolCall,
)


class _ScriptHandler(LLMHandler):
    """Handler whose streams yield ready-made ``LLMResponse`` objects (or str
    content deltas). ``agent.llm._responding_provider`` is None, so
    ``_parse_for_response`` falls back to this ``parse_response``."""

    def parse_response(self, response: Any) -> LLMResponse:
        return response

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "tool_call_id": tool_call.id, "content": str(result)}

    def _iterate_stream(self, response: Any) -> Generator:
        yield from response


def _tool_call_response() -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id="c1", name="dummy_tool", arguments={}, index=None)],
        finish_reason="tool_calls",
        raw_response=None,
    )


def _stop_response() -> LLMResponse:
    return LLMResponse(content="", tool_calls=[], finish_reason="stop", raw_response=None)


class _FakeLLM:
    def __init__(self, next_stream=None, gen_responses=None):
        self.model_id = "test-model"
        self._responding_provider = None  # route parsing to _ScriptHandler
        self._fallback_llm = None
        self._stream_reached_finish = False
        self._next_stream = next_stream or []
        self._gen_responses = list(gen_responses or [])
        self.gen_stream_tools_seen = []
        self.gen_tools_seen = []
        self.gen_stream_messages_seen = []
        self.gen_messages_seen = []

    def gen_stream(self, model, messages, tools=None, **kwargs):
        self.gen_stream_tools_seen.append(tools)
        self.gen_stream_messages_seen.append(list(messages))
        return iter(self._next_stream)

    def gen(self, model, messages, tools=None, **kwargs):
        self.gen_tools_seen.append(tools)
        self.gen_messages_seen.append(list(messages))
        return self._gen_responses.pop(0)


def _execute_tool_action(tools_dict, call):
    """Generator contract of ``agent._execute_tool_action``: may yield
    progress events; returns (tool_response, call_id)."""
    if False:  # pragma: no cover - makes this a generator
        yield None
    return ("tool ran fine", call.id)


def _fake_agent(llm):
    return SimpleNamespace(
        llm=llm,
        model_id="test-model",
        tools=None,
        tool_executor=SimpleNamespace(
            check_pause=lambda tools_dict, call, llm_class: None
        ),
        _execute_tool_action=_execute_tool_action,
    )


def _drain(gen):
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as e:
            return events, e.value


def _injected(messages, needle):
    return [m for m in messages if needle in str(m.get("content", ""))]


def _no_system_past_position_zero(messages):
    return all(m.get("role") != "system" for m in messages[1:])


class TestFinalizeMessageRole:
    def test_streaming_cap_injects_user_turn_not_trailing_system(self):
        """Site: handle_streaming cap path. One tool round at _iteration=cap-1
        forces the finalize; the instruction must be a user turn."""
        llm = _FakeLLM(next_stream=["final answer", _stop_response()])
        agent = _fake_agent(llm)
        handler = _ScriptHandler()
        messages = [
            {"role": "system", "content": "base prompt"},
            {"role": "user", "content": "question"},
        ]

        events, _ = _drain(
            handler.handle_streaming(
                agent,
                iter([_tool_call_response()]),
                {},
                messages,
                _iteration=MAX_TOOL_ITERATIONS - 1,
            )
        )

        assert "".join(e for e in events if isinstance(e, str)) == "final answer"
        sent = llm.gen_stream_messages_seen[-1]
        injected = _injected(sent, _FINALIZE_INSTRUCTION)
        assert len(injected) == 1
        assert injected[0]["role"] == "user"
        assert _no_system_past_position_zero(sent)
        # The finalize round must still close the tool loop.
        assert llm.gen_stream_tools_seen == [None]

    def test_streaming_context_limit_injects_user_turn(self):
        """Site: handle_streaming context-limit path (its own inline wording)."""
        llm = _FakeLLM(next_stream=["wrapped up", _stop_response()])
        agent = _fake_agent(llm)
        agent.context_limit_reached = True
        handler = _ScriptHandler()
        messages = [
            {"role": "system", "content": "base prompt"},
            {"role": "user", "content": "question"},
        ]

        _drain(
            handler.handle_streaming(
                agent, iter([_tool_call_response()]), {}, messages, _iteration=1
            )
        )

        sent = llm.gen_stream_messages_seen[-1]
        injected = _injected(sent, "Context window limit has been reached")
        assert len(injected) == 1
        assert injected[0]["role"] == "user"
        assert _no_system_past_position_zero(sent)
        assert llm.gen_stream_tools_seen == [None]

    def test_non_streaming_cap_injects_user_turn(self):
        """Site: handle_non_streaming cap path — 25 tool rounds then the
        forced tool-less finalize call."""
        llm = _FakeLLM(
            gen_responses=(
                [_tool_call_response()] * (MAX_TOOL_ITERATIONS - 1)
                + [
                    LLMResponse(
                        content="capped answer",
                        tool_calls=[],
                        finish_reason="stop",
                        raw_response=None,
                    )
                ]
            )
        )
        agent = _fake_agent(llm)
        handler = _ScriptHandler()
        messages = [
            {"role": "system", "content": "base prompt"},
            {"role": "user", "content": "question"},
        ]

        _, result = _drain(
            handler.handle_non_streaming(
                agent, _tool_call_response(), {}, messages
            )
        )

        assert result == "capped answer"
        sent = llm.gen_messages_seen[-1]
        injected = _injected(sent, _FINALIZE_INSTRUCTION)
        assert len(injected) == 1
        assert injected[0]["role"] == "user"
        assert _no_system_past_position_zero(sent)
        assert llm.gen_tools_seen[-1] is None  # forced tool-less finalize
