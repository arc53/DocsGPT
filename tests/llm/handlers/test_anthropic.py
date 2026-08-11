"""Unit tests for application/llm/handlers/anthropic.py.

The handler is pure duck typing over the shapes ``AnthropicLLM`` emits, so
these tests never import the anthropic SDK.
"""

import types

import pytest

from application.llm.handlers.anthropic import AnthropicLLMHandler
from application.llm.handlers.base import LLMHandler, ToolCall


def text_block(text):
    return types.SimpleNamespace(type="text", text=text)


def tool_use_block(block_id, name, payload):
    return types.SimpleNamespace(type="tool_use", id=block_id, name=name, input=payload)


def thinking_block(thinking):
    return types.SimpleNamespace(type="thinking", thinking=thinking)


def message(content, stop_reason="end_turn"):
    return types.SimpleNamespace(
        type="message", role="assistant", content=content, stop_reason=stop_reason
    )


@pytest.fixture
def handler():
    return AnthropicLLMHandler()


@pytest.mark.unit
class TestParseString:

    def test_plain_string(self, handler):
        parsed = handler.parse_response("hello")
        assert parsed.content == "hello"
        assert parsed.tool_calls == []
        assert parsed.finish_reason == "stop"


@pytest.mark.unit
class TestParseMessage:

    def test_text_blocks_joined(self, handler):
        parsed = handler.parse_response(message([text_block("a"), text_block("b")]))
        assert parsed.content == "ab"
        assert parsed.finish_reason == "stop"
        assert parsed.requires_tool_call is False

    def test_thinking_block_becomes_reasoning(self, handler):
        parsed = handler.parse_response(
            message([thinking_block("hmm"), text_block("answer")])
        )
        assert parsed.reasoning_content == "hmm"
        assert parsed.content == "answer"

    def test_tool_use_blocks_become_tool_calls(self, handler):
        parsed = handler.parse_response(
            message(
                [text_block("checking"), tool_use_block("c1", "get_weather", {"city": "Paris"})],
                stop_reason="tool_use",
            )
        )
        assert parsed.finish_reason == "tool_calls"
        assert parsed.requires_tool_call is True
        assert len(parsed.tool_calls) == 1
        call = parsed.tool_calls[0]
        assert call.id == "c1"
        assert call.name == "get_weather"
        assert call.arguments == {"city": "Paris"}

    def test_parallel_tool_use_blocks(self, handler):
        parsed = handler.parse_response(
            message(
                [tool_use_block("c1", "a", {}), tool_use_block("c2", "b", {})],
                stop_reason="tool_use",
            )
        )
        assert [c.id for c in parsed.tool_calls] == ["c1", "c2"]

    def test_max_tokens_stop_reason_maps_to_length(self, handler):
        parsed = handler.parse_response(message([text_block("x")], stop_reason="max_tokens"))
        assert parsed.finish_reason == "length"

    def test_raw_response_preserved(self, handler):
        msg = message([text_block("x")])
        assert handler.parse_response(msg).raw_response is msg


@pytest.mark.unit
class TestParseStreamChunks:

    def test_tool_use_chunk(self, handler):
        chunk = {
            "type": "tool_use",
            "id": "c1",
            "name": "get_weather",
            "arguments": '{"city": "Paris"}',
        }
        parsed = handler.parse_response(chunk)
        assert parsed.finish_reason == "tool_calls"
        assert len(parsed.tool_calls) == 1
        call = parsed.tool_calls[0]
        assert (call.id, call.name, call.arguments) == (
            "c1",
            "get_weather",
            '{"city": "Paris"}',
        )
        # Complete, index-less calls are the shape handle_streaming keeps
        # whole instead of concatenating deltas into.
        assert call.index is None

    def test_thought_chunk_is_reasoning_only(self, handler):
        parsed = handler.parse_response({"type": "thought", "thought": "hmm"})
        assert parsed.reasoning_content == "hmm"
        assert parsed.content == ""
        assert parsed.tool_calls == []

    def test_unknown_dict_chunk_is_inert(self, handler):
        parsed = handler.parse_response({"type": "something_else"})
        assert parsed.content == ""
        assert parsed.tool_calls == []
        assert parsed.finish_reason == ""


@pytest.mark.unit
class TestToolMessage:

    def test_string_result(self, handler):
        msg = handler.create_tool_message(ToolCall(id="c1", name="f", arguments={}), "ok")
        assert msg == {"role": "tool", "tool_call_id": "c1", "content": "ok"}

    def test_dict_result_serialized(self, handler):
        msg = handler.create_tool_message(
            ToolCall(id="c1", name="f", arguments={}), {"k": "v"}
        )
        assert msg["role"] == "tool"
        assert "k" in msg["content"]


@pytest.mark.unit
class TestIterateStream:

    def test_passes_chunks_through(self, handler):
        assert list(handler._iterate_stream(iter(["a", "b"]))) == ["a", "b"]


@pytest.mark.unit
class TestRegistration:

    def test_creator_returns_anthropic_handler(self):
        from application.llm.handlers.handler_creator import LLMHandlerCreator

        handler = LLMHandlerCreator.create_handler("anthropic")
        assert isinstance(handler, AnthropicLLMHandler)
        assert isinstance(handler, LLMHandler)

    def test_creator_case_insensitive(self):
        from application.llm.handlers.handler_creator import LLMHandlerCreator

        assert isinstance(
            LLMHandlerCreator.create_handler("Anthropic"), AnthropicLLMHandler
        )


@pytest.mark.unit
class TestStreamingAccumulation:
    """The tool-call shape must survive ``LLMHandler.handle_streaming``'s
    accumulator, which is where a wrong ``index`` silently corrupts args."""

    def test_complete_calls_are_not_concatenated(self, handler):
        chunks = [
            {"type": "tool_use", "id": "c1", "name": "a", "arguments": '{"x": 1}'},
            {"type": "tool_use", "id": "c2", "name": "b", "arguments": '{"y": 2}'},
        ]
        accumulated = {}
        for chunk in chunks:
            for call in handler.parse_response(chunk).tool_calls:
                assert call.index is None
                accumulated[("complete", len(accumulated))] = call
        assert [c.arguments for c in accumulated.values()] == ['{"x": 1}', '{"y": 2}']
