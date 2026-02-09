from types import SimpleNamespace

from application.llm.handlers.openai import OpenAILLMHandler
from application.llm.handlers.base import ToolCall, LLMResponse


class TestOpenAILLMHandler:
    """Test OpenAILLMHandler class."""

    def test_handler_initialization(self):
        """Test handler initialization."""
        handler = OpenAILLMHandler()
        assert handler.llm_calls == []
        assert handler.tool_calls == []

    def test_parse_response_string_input(self):
        """Test parsing string response."""
        handler = OpenAILLMHandler()
        response = "Hello, world!"
        
        result = handler.parse_response(response)
        
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello, world!"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"
        assert result.raw_response == "Hello, world!"

    def test_parse_response_with_message_content(self):
        """Test parsing response with message content."""
        handler = OpenAILLMHandler()
        
        # Mock OpenAI response structure
        mock_message = SimpleNamespace(content="Test content", tool_calls=None)
        mock_response = SimpleNamespace(message=mock_message, finish_reason="stop")
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "Test content"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"
        assert result.raw_response == mock_response

    def test_parse_response_with_delta_content(self):
        """Test parsing response with delta content (streaming)."""
        handler = OpenAILLMHandler()
        
        # Mock streaming response structure
        mock_delta = SimpleNamespace(content="Stream chunk", tool_calls=None)
        mock_response = SimpleNamespace(delta=mock_delta, finish_reason="")
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "Stream chunk"
        assert result.tool_calls == []
        assert result.finish_reason == ""
        assert result.raw_response == mock_response

    def test_parse_response_with_tool_calls(self):
        """Test parsing response with tool calls."""
        handler = OpenAILLMHandler()
        
        # Mock tool call structure
        mock_function = SimpleNamespace(name="get_weather", arguments='{"location": "NYC"}')
        mock_tool_call = SimpleNamespace(
            id="call_123",
            function=mock_function,
            index=0
        )
        mock_message = SimpleNamespace(content="", tool_calls=[mock_tool_call])
        mock_response = SimpleNamespace(message=mock_message, finish_reason="tool_calls")
        
        result = handler.parse_response(mock_response)
        
        assert result.content == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_123"
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == '{"location": "NYC"}'
        assert result.tool_calls[0].index == 0
        assert result.finish_reason == "tool_calls"

    def test_parse_response_with_multiple_tool_calls(self):
        """Test parsing response with multiple tool calls."""
        handler = OpenAILLMHandler()
        
        # Mock multiple tool calls
        mock_function1 = SimpleNamespace(name="get_weather", arguments='{"location": "NYC"}')
        mock_function2 = SimpleNamespace(name="get_time", arguments='{"timezone": "UTC"}')
        
        mock_tool_call1 = SimpleNamespace(id="call_1", function=mock_function1, index=0)
        mock_tool_call2 = SimpleNamespace(id="call_2", function=mock_function2, index=1)
        
        mock_message = SimpleNamespace(content="", tool_calls=[mock_tool_call1, mock_tool_call2])
        mock_response = SimpleNamespace(message=mock_message, finish_reason="tool_calls")
        
        result = handler.parse_response(mock_response)
        
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[1].name == "get_time"

    def test_parse_response_empty_tool_calls(self):
        """Test parsing response with empty tool_calls."""
        handler = OpenAILLMHandler()
        
        mock_message = SimpleNamespace(content="No tools needed", tool_calls=None)
        mock_response = SimpleNamespace(message=mock_message, finish_reason="stop")
        
        result = handler.parse_response(mock_response)
        
        assert result.content == "No tools needed"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    def test_parse_response_missing_attributes(self):
        """Test parsing response with missing attributes."""
        handler = OpenAILLMHandler()
        
        # Mock response with missing attributes
        mock_message = SimpleNamespace()  # No content or tool_calls
        mock_response = SimpleNamespace(message=mock_message)  # No finish_reason
        
        result = handler.parse_response(mock_response)
        
        assert result.content == ""
        assert result.tool_calls == []
        assert result.finish_reason == ""

    def test_create_tool_message(self):
        """Test creating tool message."""
        handler = OpenAILLMHandler()
        
        tool_call = ToolCall(
            id="call_123",
            name="get_weather",
            arguments={"location": "NYC"},
            index=0
        )
        result = {"temperature": "72F", "condition": "sunny"}
        
        message = handler.create_tool_message(tool_call, result)
        
        expected = {
            "role": "tool",
            "content": [
                {
                    "function_response": {
                        "name": "get_weather",
                        "response": {"result": result},
                        "call_id": "call_123",
                    }
                }
            ],
        }
        
        assert message == expected

    def test_create_tool_message_string_result(self):
        """Test creating tool message with string result."""
        handler = OpenAILLMHandler()
        
        tool_call = ToolCall(id="call_456", name="get_time", arguments={})
        result = "2023-12-01 10:30:00"
        
        message = handler.create_tool_message(tool_call, result)
        
        assert message["role"] == "tool"
        assert message["content"][0]["function_response"]["response"]["result"] == result
        assert message["content"][0]["function_response"]["call_id"] == "call_456"

    def test_iterate_stream(self):
        """Test stream iteration."""
        handler = OpenAILLMHandler()
        
        # Mock streaming response
        mock_chunks = ["chunk1", "chunk2", "chunk3"]
        
        result = list(handler._iterate_stream(mock_chunks))
        
        assert result == mock_chunks

    def test_iterate_stream_empty(self):
        """Test stream iteration with empty response."""
        handler = OpenAILLMHandler()
        
        result = list(handler._iterate_stream([]))
        
        assert result == []

    def test_iterate_stream_preserves_thought_events(self):
        """Test stream iteration preserves provider-emitted thought events."""
        handler = OpenAILLMHandler()

        mock_chunks = [
            {"type": "thought", "thought": "first thought"},
            "answer token",
        ]

        result = list(handler._iterate_stream(mock_chunks))

        assert result == [
            {"type": "thought", "thought": "first thought"},
            "answer token",
        ]

    def test_parse_response_tool_call_missing_attributes(self):
        """Test parsing tool calls with missing attributes."""
        handler = OpenAILLMHandler()
        
        # Mock tool call with missing attributes
        mock_function = SimpleNamespace()  # No name or arguments
        mock_tool_call = SimpleNamespace(function=mock_function)  # No id or index
        
        mock_message = SimpleNamespace(content="", tool_calls=[mock_tool_call])
        mock_response = SimpleNamespace(message=mock_message, finish_reason="tool_calls")
        
        result = handler.parse_response(mock_response)
        
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == ""
        assert result.tool_calls[0].name == ""
        assert result.tool_calls[0].arguments == ""
        assert result.tool_calls[0].index is None
