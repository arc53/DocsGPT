from unittest.mock import Mock, patch
from types import SimpleNamespace
import uuid

from application.llm.handlers.google import GoogleLLMHandler
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
        """Test creating tool message."""
        handler = GoogleLLMHandler()
        
        tool_call = ToolCall(
            id="call_123",
            name="get_weather",
            arguments={"location": "Tokyo"},
            index=0
        )
        result = {"temperature": "25C", "condition": "cloudy"}
        
        message = handler.create_tool_message(tool_call, result)
        
        expected = {
            "role": "model",
            "content": [
                {
                    "function_response": {
                        "name": "get_weather",
                        "response": {"result": result},
                    }
                }
            ],
        }
        
        assert message == expected

    def test_create_tool_message_string_result(self):
        """Test creating tool message with string result."""
        handler = GoogleLLMHandler()
        
        tool_call = ToolCall(id="call_456", name="get_time", arguments={})
        result = "2023-12-01 15:30:00 JST"
        
        message = handler.create_tool_message(tool_call, result)
        
        assert message["role"] == "model"
        assert message["content"][0]["function_response"]["response"]["result"] == result
        assert message["content"][0]["function_response"]["name"] == "get_time"

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
