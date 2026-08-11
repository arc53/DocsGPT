"""Pre-send context gate and per-tool-result cap.

Covers the two guards that keep tool-loop payloads inside the model's
context window: ``_bound_tool_response_for_llm`` (one giant tool result
must not enter the message array uncapped) and
``BaseAgent._enforce_context_window`` (an over-window payload is shrunk
or refused *before* the usage decorators run).
"""

from unittest.mock import Mock, patch

import pytest

from application.agents.base import BaseAgent
from application.llm.handlers.base import (
    LLMHandler,
    LLMResponse,
    ToolCall,
    _bound_tool_response_for_llm,
)


class GateHandler(LLMHandler):
    def parse_response(self, response):
        kind = response.get("kind")
        if kind == "tool_call":
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="1", name="t", arguments="{}", index=0)],
                finish_reason="tool_calls",
                raw_response=None,
            )
        return LLMResponse(
            content="", tool_calls=[], finish_reason="stop", raw_response=None
        )

    def create_tool_message(self, tool_call, result):
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result if isinstance(result, str) else str(result),
        }

    def _iterate_stream(self, response):
        yield from response


class MockAgent(BaseAgent):
    def _gen_inner(self, query, log_context=None):
        yield {"answer": "test"}


@pytest.fixture
def agent():
    a = MockAgent(
        endpoint="test",
        llm_name="openai",
        model_id="gpt-4o",
        api_key="test-key",
    )
    a.llm = Mock()
    return a


@pytest.mark.unit
class TestBoundToolResponse:
    def test_small_result_passes_through_unchanged(self):
        result = {"status": "ok", "data": "small"}
        assert _bound_tool_response_for_llm(result) is result

    def test_oversized_result_is_truncated(self, monkeypatch):
        monkeypatch.setattr(
            "application.core.settings.settings.TOOL_RESULT_MAX_TOKENS",
            30,
            raising=False,
        )
        big = "word " * 2000
        bounded = _bound_tool_response_for_llm(big)
        assert "tool result truncated" in bounded
        assert len(bounded) < len(big)

    def test_zero_cap_disables_truncation(self, monkeypatch):
        monkeypatch.setattr(
            "application.core.settings.settings.TOOL_RESULT_MAX_TOKENS",
            0,
            raising=False,
        )
        big = "word " * 2000
        assert _bound_tool_response_for_llm(big) is big

    def test_handle_tool_calls_bounds_the_llm_copy(self, monkeypatch):
        """The message handed to the LLM is capped even though the executor
        returned the full result (journal/persistence keep the original)."""
        monkeypatch.setattr(
            "application.core.settings.settings.TOOL_RESULT_MAX_TOKENS",
            30,
            raising=False,
        )
        handler = GateHandler()
        big = "word " * 2000

        def fake_executor(tools_dict, call):
            yield {"type": "tool_call", "data": {}}
            return big, "call_1"

        mock_agent = Mock()
        mock_agent._check_context_limit = Mock(return_value=False)
        mock_agent._execute_tool_action = Mock(side_effect=fake_executor)
        mock_agent.tool_executor.check_pause = Mock(return_value=None)

        gen = handler.handle_tool_calls(
            mock_agent,
            [ToolCall(id="call_1", name="t", arguments="{}", index=0)],
            {},
            [],
        )
        while True:
            try:
                next(gen)
            except StopIteration as e:
                messages, pending = e.value
                break

        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert "tool result truncated" in tool_messages[0]["content"]
        assert len(tool_messages[0]["content"]) < len(big)
        assert pending is None


@pytest.mark.unit
class TestEnforceContextWindow:
    def test_within_window_returns_messages_untouched(self, agent):
        messages = [{"role": "user", "content": "hello"}]
        with patch(
            "application.core.model_utils.get_token_limit", return_value=1000
        ):
            assert agent._enforce_context_window(messages) is messages

    def test_over_window_shrinks_tool_messages(self, agent):
        messages = [
            {"role": "user", "content": "question"},
            {"role": "tool", "tool_call_id": "1", "content": "word " * 2000},
        ]
        with patch(
            "application.core.model_utils.get_token_limit", return_value=1000
        ):
            shrunk = agent._enforce_context_window(messages)
        tool_content = shrunk[1]["content"]
        assert "truncated to fit context limit" in tool_content
        assert agent._calculate_current_context_tokens(shrunk) < 1000

    def test_impossible_payload_raises_before_dispatch(self, agent):
        # The bulk is NOT in tool messages, so shrinking cannot help.
        messages = [{"role": "user", "content": "word " * 3000}]
        with patch(
            "application.core.model_utils.get_token_limit", return_value=100
        ):
            with pytest.raises(ValueError, match="exceeds the model's context window"):
                agent._enforce_context_window(messages)

    def test_streaming_loop_gates_before_next_round(self):
        """handle_streaming must run the gate before dispatching the next
        round's gen_stream."""
        handler = GateHandler()
        order = []

        mock_agent = Mock()
        mock_agent.context_limit_reached = False
        mock_agent.tools = []
        mock_agent.model_id = "m"
        mock_agent._enforce_context_window = Mock(
            side_effect=lambda msgs: (order.append("gate"), msgs)[1]
        )
        mock_agent.llm.gen_stream = Mock(
            side_effect=lambda **kw: (order.append("dispatch"), [{"kind": "stop"}])[1]
        )

        def fake_tool_calls(a, calls, tools_dict, messages, **kwargs):
            yield {"type": "tool_call", "data": {}}
            return messages, None

        with patch.object(handler, "handle_tool_calls", fake_tool_calls):
            list(
                handler.handle_streaming(
                    mock_agent, [{"kind": "tool_call"}], {}, []
                )
            )

        assert order == ["gate", "dispatch"]


@pytest.mark.unit
class TestTinyCapTruncation:
    def test_tiny_cap_never_returns_more_than_original(self, monkeypatch):
        """keep==0 used to produce marker + FULL text (text[-0:] is the
        whole string) — a 'truncation' that grows the payload."""
        monkeypatch.setattr(
            "application.core.settings.settings.TOOL_RESULT_MAX_TOKENS",
            1,
            raising=False,
        )
        big = "word " * 500
        bounded = _bound_tool_response_for_llm(big)
        assert len(bounded) < len(big)
        assert "truncated" in bounded
