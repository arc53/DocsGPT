import json
from unittest.mock import Mock, patch
from types import SimpleNamespace
import uuid

from application.llm.handlers.google import (
    GoogleLLMHandler,
    _decode_thought_signature,
    _encode_thought_signature,
)
from application.llm.handlers.base import ToolCall, LLMResponse


class TestGoogleLLMHandler:
    """Test GoogleLLMHandler class."""

    def test_handler_initialization(self):
        """Test handler initialization."""
        handler = GoogleLLMHandler()
        assert handler.llm_calls == []
        assert handler.tool_calls == []

    def test_parse_response_string_input(self):
        """Test parsing string response."""
        handler = GoogleLLMHandler()
        response = "Hello from Google!"
        
        result = handler.parse_response(response)
        
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello from Google!"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"
        assert result.raw_response == "Hello from Google!"

    def test_parse_response_with_candidates_text_only(self):
        """Test parsing response with candidates containing only text."""
        handler = GoogleLLMHandler()
        
        mock_part = SimpleNamespace(text="Google response text")
        mock_content = SimpleNamespace(parts=[mock_part])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "Google response text"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"
        assert result.raw_response == mock_response

    def test_parse_response_with_multiple_text_parts(self):
        """Test parsing response with multiple text parts."""
        handler = GoogleLLMHandler()
        
        mock_part1 = SimpleNamespace(text="First part")
        mock_part2 = SimpleNamespace(text="Second part")
        mock_content = SimpleNamespace(parts=[mock_part1, mock_part2])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "First part Second part"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    @patch('uuid.uuid4')
    def test_parse_response_with_function_call(self, mock_uuid):
        """Test parsing response with function call."""
        mock_uuid.return_value = Mock(spec=uuid.UUID)
        mock_uuid.return_value.__str__ = Mock(return_value="test-uuid-123")
        
        handler = GoogleLLMHandler()
        
        mock_function_call = SimpleNamespace(
            name="get_weather",
            args={"location": "San Francisco"}
        )
        mock_part = SimpleNamespace(function_call=mock_function_call)
        mock_content = SimpleNamespace(parts=[mock_part])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])
        
        result = handler.parse_response(mock_response)
        
        assert result.content == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "test-uuid-123"
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"location": "San Francisco"}
        assert result.finish_reason == "tool_calls"

    @patch('uuid.uuid4')
    def test_parse_response_with_mixed_parts(self, mock_uuid):
        """Test parsing response with both text and function call parts."""
        mock_uuid.return_value = Mock(spec=uuid.UUID)
        mock_uuid.return_value.__str__ = Mock(return_value="test-uuid-456")
        
        handler = GoogleLLMHandler()
        
        mock_text_part = SimpleNamespace(text="I'll check the weather for you.")
        mock_function_call = SimpleNamespace(
            name="get_weather",
            args={"location": "NYC"}
        )
        mock_function_part = SimpleNamespace(function_call=mock_function_call)
        
        mock_content = SimpleNamespace(parts=[mock_text_part, mock_function_part])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "I'll check the weather for you."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.finish_reason == "tool_calls"

    def test_parse_response_empty_candidates(self):
        """Test parsing response with empty candidates."""
        handler = GoogleLLMHandler()
        
        mock_response = SimpleNamespace(candidates=[])
        
        result = handler.parse_response(mock_response)
        
        assert result.content == ""
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    def test_parse_response_parts_with_none_text(self):
        """Test parsing response with parts that have None text."""
        handler = GoogleLLMHandler()
        
        mock_part1 = SimpleNamespace(text=None)
        mock_part2 = SimpleNamespace(text="Valid text")
        mock_content = SimpleNamespace(parts=[mock_part1, mock_part2])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "Valid text"

    def test_parse_response_parts_without_text_attribute(self):
        """Test parsing response with parts missing text attribute."""
        handler = GoogleLLMHandler()
        
        mock_part1 = SimpleNamespace() 
        mock_part2 = SimpleNamespace(text="Valid text")
        mock_content = SimpleNamespace(parts=[mock_part1, mock_part2])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "Valid text"

    @patch('uuid.uuid4')
    def test_parse_response_direct_function_call(self, mock_uuid):
        """Test parsing response with direct function call (not in candidates)."""
        mock_uuid.return_value = Mock(spec=uuid.UUID)
        mock_uuid.return_value.__str__ = Mock(return_value="direct-uuid-789")
        
        handler = GoogleLLMHandler()
        
        mock_function_call = SimpleNamespace(
            name="calculate",
            args={"expression": "2+2"}
        )
        mock_response = SimpleNamespace(
            function_call=mock_function_call,
            text="The calculation result is:"
        )
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "The calculation result is:"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "direct-uuid-789"
        assert result.tool_calls[0].name == "calculate"
        assert result.tool_calls[0].arguments == {"expression": "2+2"}
        assert result.finish_reason == "tool_calls"

    def test_parse_response_direct_function_call_no_text(self):
        """Test parsing response with direct function call and no text."""
        handler = GoogleLLMHandler()
        
        mock_function_call = SimpleNamespace(
            name="get_data",
            args={"id": 123}
        )
        mock_response = SimpleNamespace(function_call=mock_function_call)
        
        result = handler.parse_response(mock_response)
        
        assert result.content == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_data"
        assert result.finish_reason == "tool_calls"

    def test_create_tool_message(self):
        """Test creating tool message in standard format."""
        handler = GoogleLLMHandler()

        tool_call = ToolCall(
            id="call_123",
            name="get_weather",
            arguments={"location": "Tokyo"},
            index=0
        )
        result = {"temperature": "25C", "condition": "cloudy"}

        message = handler.create_tool_message(tool_call, result)

        assert message["role"] == "tool"
        assert message["tool_call_id"] == "call_123"
        import json
        assert json.loads(message["content"]) == result

    def test_create_tool_message_string_result(self):
        """Test creating tool message with string result."""
        handler = GoogleLLMHandler()

        tool_call = ToolCall(id="call_456", name="get_time", arguments={})
        result = "2023-12-01 15:30:00 JST"

        message = handler.create_tool_message(tool_call, result)

        assert message["role"] == "tool"
        assert message["tool_call_id"] == "call_456"
        assert message["content"] == result

    def test_create_tool_message_with_pg_native_types(self):
        # PostgresTool returns dicts containing datetime / UUID / Decimal
        # / bytes when the user runs a SELECT against timestamptz / uuid /
        # numeric / bytea columns. The shared PGNativeJSONEncoder handles
        # all five types lossless — bytes round-trip through base64.
        import base64
        from datetime import datetime, date, timezone
        from decimal import Decimal
        from uuid import UUID

        handler = GoogleLLMHandler()
        tool_call = ToolCall(id="call_pg", name="run_sql", arguments={})
        result = {
            "data": [
                {
                    "id": UUID("12345678-1234-5678-1234-567812345678"),
                    "created_at": datetime(2026, 5, 2, 12, 14, 32, tzinfo=timezone.utc),
                    "scheduled_for": date(2026, 6, 1),
                    "amount": Decimal("123.45"),
                    "blob": b"\x00\x01\xff",
                }
            ]
        }

        message = handler.create_tool_message(tool_call, result)

        assert message["role"] == "tool"
        decoded = json.loads(message["content"])
        row = decoded["data"][0]
        assert row["id"] == "12345678-1234-5678-1234-567812345678"
        assert row["created_at"] == "2026-05-02T12:14:32+00:00"
        assert row["scheduled_for"] == "2026-06-01"
        assert row["amount"] == "123.45"
        assert base64.b64decode(row["blob"]) == b"\x00\x01\xff"

    def test_iterate_stream(self):
        """Test stream iteration."""
        handler = GoogleLLMHandler()
        
        mock_chunks = ["chunk1", "chunk2", "chunk3"]
        
        result = list(handler._iterate_stream(mock_chunks))
        
        assert result == mock_chunks

    def test_iterate_stream_empty(self):
        """Test stream iteration with empty response."""
        handler = GoogleLLMHandler()
        
        result = list(handler._iterate_stream([]))
        
        assert result == []

    def test_iterate_stream_preserves_thought_events(self):
        """Test stream iteration preserves provider-emitted thought events."""
        handler = GoogleLLMHandler()

        mock_chunks = [
            {"type": "thought", "thought": "first thought"},
            "answer token",
        ]

        result = list(handler._iterate_stream(mock_chunks))

        assert result == [
            {"type": "thought", "thought": "first thought"},
            "answer token",
        ]

    def test_parse_response_parts_without_function_call_attribute(self):
        """Test parsing response with parts missing function_call attribute."""
        handler = GoogleLLMHandler()

        mock_part = SimpleNamespace(text="Normal text")
        mock_content = SimpleNamespace(parts=[mock_part])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])

        result = handler.parse_response(mock_response)

        assert result.content == "Normal text"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    def test_parse_response_function_call_with_bytes_thought_signature_is_json_serializable(self):
        """Gemini 3 returns thought_signature as bytes; the parsed ToolCall
        must remain json-serialisable so the SSE writer doesn't crash."""
        handler = GoogleLLMHandler()
        signature_bytes = b"\x00\x01gemini-binary-sig\xff"

        mock_function_call = SimpleNamespace(
            name="search_docs", args={"query": "workflows"}
        )
        mock_part = SimpleNamespace(
            function_call=mock_function_call,
            thought_signature=signature_bytes,
        )
        mock_content = SimpleNamespace(parts=[mock_part])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(candidates=[mock_candidate])

        result = handler.parse_response(mock_response)

        sig = result.tool_calls[0].thought_signature
        assert isinstance(sig, str)
        json.dumps({"thought_signature": sig})  # would raise on bytes

        # Round-trip must be lossless so we can replay the call to Gemini.
        assert _decode_thought_signature(sig) == signature_bytes

    def test_parse_response_direct_call_with_bytes_thought_signature(self):
        """Streaming path (direct Part, no candidates) — same invariant."""
        handler = GoogleLLMHandler()
        signature_bytes = b"\xde\xad\xbe\xef"

        mock_response = SimpleNamespace(
            function_call=SimpleNamespace(name="t", args={}),
            thought_signature=signature_bytes,
        )

        result = handler.parse_response(mock_response)

        sig = result.tool_calls[0].thought_signature
        assert isinstance(sig, str)
        assert _decode_thought_signature(sig) == signature_bytes


class TestThoughtSignatureRoundtrip:
    """Encoder / decoder helpers for Gemini's thought_signature field."""

    def test_encode_bytes_to_str(self):
        assert _encode_thought_signature(b"abc") == "YWJj"

    def test_encode_str_passthrough(self):
        assert _encode_thought_signature("YWJj") == "YWJj"

    def test_encode_none(self):
        assert _encode_thought_signature(None) is None

    def test_decode_str_to_bytes(self):
        assert _decode_thought_signature("YWJj") == b"abc"

    def test_decode_bytes_passthrough(self):
        assert _decode_thought_signature(b"abc") == b"abc"

    def test_decode_none(self):
        assert _decode_thought_signature(None) is None

    def test_decode_invalid_base64_falls_back_to_input(self):
        # If the value somehow isn't base64, we don't want to lose it —
        # return the original string so the SDK gets *something* (and
        # Gemini surfaces a clearer error than "decode failed in our code").
        assert _decode_thought_signature("not!valid!b64!") == "not!valid!b64!"

    def test_idempotent_encode_decode_roundtrip(self):
        original = b"\x00\xff\x10\x20gemini\x00"
        assert _decode_thought_signature(_encode_thought_signature(original)) == original
