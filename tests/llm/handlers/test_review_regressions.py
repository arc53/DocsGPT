"""Regression tests from the adversarial review of the stream-drain change.

Covers: Google-style index-less parallel tool calls (complete payloads must
never be merged), trailing-frame failures after finish_reason (must not fail
or fallback-restream a delivered answer), and the in-memory compression
path surviving the negative-savings ValueError via minimal pruning.
"""

from unittest.mock import Mock, patch

import pytest

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


class ScriptedHandler(LLMHandler):
    """Chunks are dicts carrying a prebuilt LLMResponse under 'resp'."""

    def parse_response(self, response):
        return response["resp"]

    def create_tool_message(self, tool_call, result):
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": str(result),
        }

    def _iterate_stream(self, response):
        yield from response


def _agent(llm=None):
    agent = Mock()
    agent.llm = llm or Mock()
    agent.tools = []
    agent.model_id = "test-model"
    agent.context_limit_reached = False
    agent._check_context_limit = Mock(return_value=False)
    agent._enforce_context_window = Mock(side_effect=lambda msgs: msgs)
    # Explicit falsy values: auto-created Mock attributes are truthy and
    # would trip the provider-finished check in the drain loop.
    agent.llm._stream_reached_finish = False
    agent.llm._fallback_llm = None
    return agent


@pytest.mark.unit
class TestIndexlessParallelToolCalls:
    def test_google_style_parallel_calls_stay_separate(self):
        """Two complete index-less calls (dict arguments) must reach
        handle_tool_calls as two distinct calls — the merge branch would
        raise ``dict += dict`` or execute tool_B with tool_A's args."""
        handler = ScriptedHandler()
        chunk_a = {
            "resp": LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="a", name="tool_A", arguments={"x": 1}, index=None)
                ],
                finish_reason="tool_calls",
                raw_response=None,
            )
        }
        chunk_b = {
            "resp": LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="b", name="tool_B", arguments={"y": 2}, index=None)
                ],
                finish_reason="tool_calls",
                raw_response=None,
            )
        }
        stop_round = [
            {
                "resp": LLMResponse(
                    content="done",
                    tool_calls=[],
                    finish_reason="stop",
                    raw_response=None,
                )
            }
        ]

        received_calls = []

        def fake_tool_calls(agent, calls, tools_dict, messages, **kwargs):
            received_calls.extend(calls)
            yield {"type": "tool_call", "data": {}}
            return messages, None

        llm = Mock()
        llm.gen_stream = Mock(return_value=stop_round)
        agent = _agent(llm)

        with patch.object(handler, "handle_tool_calls", fake_tool_calls):
            list(handler.handle_streaming(agent, [chunk_a, chunk_b], {}, []))

        assert [(c.name, c.arguments) for c in received_calls] == [
            ("tool_A", {"x": 1}),
            ("tool_B", {"y": 2}),
        ]

    def test_indexed_string_deltas_still_merge(self):
        """OpenAI-style indexed argument fragments keep concatenating."""
        handler = ScriptedHandler()
        frag1 = {
            "resp": LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c1", name="t", arguments='{"q":', index=0)],
                finish_reason=None,
                raw_response=None,
            )
        }
        frag2 = {
            "resp": LLMResponse(
                content="",
                tool_calls=[ToolCall(id="", name="", arguments='"x"}', index=0)],
                finish_reason="tool_calls",
                raw_response=None,
            )
        }
        stop_round = [
            {
                "resp": LLMResponse(
                    content="done",
                    tool_calls=[],
                    finish_reason="stop",
                    raw_response=None,
                )
            }
        ]

        received_calls = []

        def fake_tool_calls(agent, calls, tools_dict, messages, **kwargs):
            received_calls.extend(calls)
            yield {"type": "tool_call", "data": {}}
            return messages, None

        llm = Mock()
        llm.gen_stream = Mock(return_value=stop_round)
        agent = _agent(llm)

        with patch.object(handler, "handle_tool_calls", fake_tool_calls):
            list(handler.handle_streaming(agent, [frag1, frag2], {}, []))

        assert len(received_calls) == 1
        assert received_calls[0].arguments == '{"q":"x"}'


class FailingTailStream:
    """Yields chunks, then raises — models a reset in the trailing frames."""

    def __init__(self, chunks, error):
        self._chunks = chunks
        self._error = error

    def __iter__(self):
        yield from self._chunks
        raise self._error


@pytest.mark.unit
class TestTrailingFrameFailures:
    def _stop_chunk(self, text="hello"):
        return {
            "resp": LLMResponse(
                content=text,
                tool_calls=[],
                finish_reason="stop",
                raw_response=None,
            )
        }

    def test_failure_after_finish_is_swallowed(self):
        handler = ScriptedHandler()
        stream = FailingTailStream(
            [self._stop_chunk()], RuntimeError("reset in trailing frame")
        )
        out = list(handler.handle_streaming(_agent(), stream, {}, []))
        assert "hello" in out

    def test_failure_before_finish_still_propagates(self):
        handler = ScriptedHandler()
        stream = FailingTailStream([], RuntimeError("early failure"))
        with pytest.raises(RuntimeError, match="early failure"):
            list(handler.handle_streaming(_agent(), stream, {}, []))

    def test_final_round_failure_after_provider_finish_is_swallowed(self):
        """The final answer round never surfaces a parseable 'stop' chunk
        (content arrives as bare strings), so the swallow must key off the
        LLM-level _stream_reached_finish flag."""
        handler = ScriptedHandler()
        agent = _agent()
        agent.llm._stream_reached_finish = True
        # Bare string content, no parseable finish chunk, then a trailing
        # frame failure — the OpenAI chat final-round shape.
        stream = FailingTailStream(
            ["the full answer"], RuntimeError("reset in trailing frame")
        )
        out = list(handler.handle_streaming(agent, stream, {}, []))
        assert "the full answer" in out

    def test_fallback_served_stream_failure_after_finish_is_swallowed(self):
        """When the fallback delivered the answer, its finish flag lives on
        the fallback instance — the swallow must check it there too."""
        handler = ScriptedHandler()
        agent = _agent()
        agent.llm._stream_reached_finish = False
        agent.llm._fallback_llm = Mock()
        agent.llm._fallback_llm._stream_reached_finish = True
        stream = FailingTailStream(
            ["fallback answer"], RuntimeError("reset in trailing frame")
        )
        out = list(handler.handle_streaming(agent, stream, {}, []))
        assert "fallback answer" in out


@pytest.mark.unit
class TestInMemoryCompressionNegativeSavings:
    def test_value_error_falls_back_to_minimal_pruning(self):
        """The negative-savings ValueError from compress_conversation must
        route to _prune_messages_minimal, not kill the tool loop."""
        handler = ScriptedHandler()
        agent = _agent()
        agent.model_id = "gpt-4o"
        agent.decoded_token = {"sub": "u1"}
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]
        pruned = [{"role": "system", "content": "pruned"}]

        with patch.object(
            handler,
            "_build_conversation_from_messages",
            return_value={"queries": [{"prompt": "q1", "response": "a1"}]},
        ), patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="k",
        ), patch(
            "application.llm.llm_creator.LLMCreator.create_llm",
            return_value=Mock(),
        ), patch(
            "application.api.answer.services.compression.service."
            "CompressionService.compress_conversation",
            side_effect=ValueError(
                "Compression did not reduce token count (10 → 20); "
                "keeping original history"
            ),
        ), patch.object(
            handler, "_prune_messages_minimal", return_value=pruned
        ):
            ok, rebuilt = handler._perform_in_memory_compression(agent, messages)

        assert ok is True
        assert rebuilt == pruned
        assert agent.context_limit_reached is False
