"""Per-round token-usage persistence in the streaming tool loop.

Regression tests for the duplicate ``token_usage`` rows bug: each tool
round's provider stream must be consumed to exhaustion *before* the next
round starts, so the ``stream_token_usage`` ``finally`` persists one row
per round with that round's own counts — never a late flush at request
teardown that adopts the final round's shared ``_last_usage``.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from application import usage as usage_mod
from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


class RecordingStream:
    """Iterable stream that records whether it was fully consumed."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.exhausted = False

    def __iter__(self):
        for chunk in self._chunks:
            yield chunk
        self.exhausted = True


class RoundHandler(LLMHandler):
    """Minimal concrete handler: chunk dicts drive the parse result."""

    def parse_response(self, response):
        kind = response.get("kind")
        if kind == "tool_call":
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="1", name="t", arguments="{}", index=0)],
                finish_reason="tool_calls",
                raw_response=None,
            )
        if kind == "content":
            return LLMResponse(
                content="hello",
                tool_calls=[],
                finish_reason=None,
                raw_response=None,
            )
        if kind == "stop":
            return LLMResponse(
                content="",
                tool_calls=[],
                finish_reason="stop",
                raw_response=None,
            )
        # Terminal usage-only chunk: no content, no finish_reason.
        return LLMResponse(
            content="", tool_calls=[], finish_reason=None, raw_response=None
        )

    def create_tool_message(self, tool_call, result):
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": str(result),
        }

    def _iterate_stream(self, response):
        yield from response


def _agent(llm):
    agent = Mock()
    agent.llm = llm
    agent.tools = []
    agent.model_id = "test-model"
    agent.context_limit_reached = False
    agent._check_context_limit = Mock(return_value=False)
    agent._enforce_context_window = Mock(side_effect=lambda msgs: msgs)
    return agent


class TestStreamDrainedBeforeNextRound:
    def test_round_stream_exhausted_before_tool_handling(self):
        """The round's generator must be fully consumed (usage chunk and
        all) before handle_tool_calls runs — not abandoned mid-iteration."""
        handler = RoundHandler()
        round1 = RecordingStream([{"kind": "tool_call"}, {"kind": "usage"}])
        round2 = RecordingStream([{"kind": "stop"}])

        exhausted_at_tool_time = []

        def fake_tool_calls(agent, calls, tools_dict, messages, **kwargs):
            exhausted_at_tool_time.append(round1.exhausted)
            yield {"type": "tool_call", "data": {}}
            return messages, None

        llm = Mock()
        llm.gen_stream = Mock(return_value=round2)
        agent = _agent(llm)

        with patch.object(handler, "handle_tool_calls", fake_tool_calls):
            list(handler.handle_streaming(agent, round1, {}, []))

        assert exhausted_at_tool_time == [True]
        assert round2.exhausted is True

    def test_stop_round_drains_trailing_usage_chunk(self):
        """A round that finishes with ``stop`` still consumes the trailing
        usage-only chunk (Chat Completions include_usage arrives after the
        finish_reason chunk)."""
        handler = RoundHandler()
        stream = RecordingStream(
            [{"kind": "content"}, {"kind": "stop"}, {"kind": "usage"}]
        )
        agent = _agent(Mock())

        out = list(handler.handle_streaming(agent, stream, {}, []))

        assert stream.exhausted is True
        assert "hello" in out


class TestPerRoundUsageRows:
    def test_one_row_per_round_with_own_counts(self):
        """Two rounds → two persisted rows, each with that round's own
        provider counts (not two copies of the final round's)."""
        handler = RoundHandler()

        class FakeLLM:
            def __init__(self):
                self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}
                self.decoded_token = {"sub": "u1"}
                self.user_api_key = None
                self.agent_id = None
                self._last_usage = None
                self._last_usage_claimed = False
                self.round = 0

            def gen_stream(self, model, messages, tools=None, **kwargs):
                wrapped = usage_mod.stream_token_usage(FakeLLM._raw_gen_stream)
                return wrapped(self, model, messages, True, tools, **kwargs)

            def _raw_gen_stream(self, model, messages, stream, tools, **kwargs):
                self._last_usage = None
                self._last_usage_claimed = False
                self.round += 1
                current = self.round
                if current == 1:
                    yield {"kind": "tool_call"}
                else:
                    yield {"kind": "content"}
                    yield {"kind": "stop"}
                # Provider reports usage in the terminal chunk, after the
                # finish_reason — only a drained stream ever reaches this.
                self._last_usage = {
                    "prompt_tokens": 100 * current,
                    "completion_tokens": 10 * current,
                }
                self._last_usage_claimed = False

        llm = FakeLLM()
        agent = _agent(llm)

        def fake_tool_calls(a, calls, tools_dict, messages, **kwargs):
            yield {"type": "tool_call", "data": {}}
            return messages, None

        rows = []
        with patch.object(
            usage_mod,
            "_persist_call_usage",
            side_effect=lambda llm_, cu: rows.append(dict(cu)),
        ):
            with patch.object(handler, "handle_tool_calls", fake_tool_calls):
                first = llm.gen_stream(
                    model="m", messages=[{"role": "user", "content": "hi"}]
                )
                list(handler.handle_streaming(agent, first, {}, []))

        assert len(rows) == 2
        assert rows[0] == {"prompt_tokens": 100, "generated_tokens": 10}
        assert rows[1] == {"prompt_tokens": 200, "generated_tokens": 20}


class TestPreferProviderUsageClaim:
    def test_usage_claimed_only_once(self):
        llm = SimpleNamespace(
            _last_usage={"prompt_tokens": 7, "completion_tokens": 9},
            _last_usage_claimed=False,
        )
        estimate = {"prompt_tokens": 42, "generated_tokens": 1}

        first = usage_mod._prefer_provider_usage(llm, dict(estimate))
        assert first == {"prompt_tokens": 7, "generated_tokens": 9}
        assert llm._last_usage_claimed is True

        second = usage_mod._prefer_provider_usage(llm, dict(estimate))
        assert second == dict(estimate)

    def test_fresh_usage_resets_claim(self):
        llm = SimpleNamespace(
            _last_usage={"prompt_tokens": 7, "completion_tokens": 9},
            _last_usage_claimed=False,
        )
        usage_mod._prefer_provider_usage(llm, {"prompt_tokens": 1, "generated_tokens": 1})

        # Provider records a new call's usage → unclaimed again.
        llm._last_usage = {"prompt_tokens": 70, "completion_tokens": 90}
        llm._last_usage_claimed = False

        result = usage_mod._prefer_provider_usage(
            llm, {"prompt_tokens": 2, "generated_tokens": 2}
        )
        assert result == {"prompt_tokens": 70, "generated_tokens": 90}

    def test_missing_usage_keeps_estimate(self):
        llm = SimpleNamespace(_last_usage=None, _last_usage_claimed=False)
        estimate = {"prompt_tokens": 5, "generated_tokens": 3}
        assert usage_mod._prefer_provider_usage(llm, dict(estimate)) == estimate
