import pytest
from unittest.mock import Mock, patch
from typing import Any, Dict, Generator

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


class TestToolCall:
    """Test ToolCall dataclass."""

    def test_tool_call_creation(self):
        """Test basic ToolCall creation."""
        tool_call = ToolCall(
            id="test_id",
            name="test_function",
            arguments={"arg1": "value1"},
            index=0
        )
        assert tool_call.id == "test_id"
        assert tool_call.name == "test_function"
        assert tool_call.arguments == {"arg1": "value1"}
        assert tool_call.index == 0

    def test_tool_call_from_dict(self):
        """Test ToolCall creation from dictionary."""
        data = {
            "id": "call_123",
            "name": "get_weather",
            "arguments": {"location": "New York"},
            "index": 1
        }
        tool_call = ToolCall.from_dict(data)
        assert tool_call.id == "call_123"
        assert tool_call.name == "get_weather"
        assert tool_call.arguments == {"location": "New York"}
        assert tool_call.index == 1

    def test_tool_call_from_dict_missing_fields(self):
        """Test ToolCall creation with missing fields."""
        data = {"name": "test_func"}
        tool_call = ToolCall.from_dict(data)
        assert tool_call.id == ""
        assert tool_call.name == "test_func"
        assert tool_call.arguments == {}
        assert tool_call.index is None


class TestLLMResponse:
    """Test LLMResponse dataclass."""

    def test_llm_response_creation(self):
        """Test basic LLMResponse creation."""
        tool_calls = [ToolCall(id="1", name="func", arguments={})]
        response = LLMResponse(
            content="Hello",
            tool_calls=tool_calls,
            finish_reason="tool_calls",
            raw_response={"test": "data"}
        )
        assert response.content == "Hello"
        assert len(response.tool_calls) == 1
        assert response.finish_reason == "tool_calls"
        assert response.raw_response == {"test": "data"}

    def test_requires_tool_call_true(self):
        """Test requires_tool_call property when tool calls are needed."""
        tool_calls = [ToolCall(id="1", name="func", arguments={})]
        response = LLMResponse(
            content="",
            tool_calls=tool_calls,
            finish_reason="tool_calls",
            raw_response={}
        )
        assert response.requires_tool_call is True

    def test_requires_tool_call_false_no_tools(self):
        """Test requires_tool_call property when no tool calls."""
        response = LLMResponse(
            content="Hello",
            tool_calls=[],
            finish_reason="stop",
            raw_response={}
        )
        assert response.requires_tool_call is False

    def test_requires_tool_call_false_wrong_finish_reason(self):
        """Test requires_tool_call property with tools but wrong finish reason."""
        tool_calls = [ToolCall(id="1", name="func", arguments={})]
        response = LLMResponse(
            content="Hello",
            tool_calls=tool_calls,
            finish_reason="stop",
            raw_response={}
        )
        assert response.requires_tool_call is False


class ConcreteHandler(LLMHandler):
    """Concrete implementation for testing abstract base class."""

    def parse_response(self, response: Any) -> LLMResponse:
        return LLMResponse(
            content=str(response),
            tool_calls=[],
            finish_reason="stop",
            raw_response=response
        )

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {
            "role": "tool",
            "content": str(result),
            "tool_call_id": tool_call.id
        }

    def _iterate_stream(self, response: Any) -> Generator:
        for chunk in response:
            yield chunk


class TestLLMHandler:
    """Test LLMHandler base class."""

    def test_handler_initialization(self):
        """Test handler initialization."""
        handler = ConcreteHandler()
        assert handler.llm_calls == []
        assert handler.tool_calls == []

    def test_prepare_messages_no_attachments(self):
        """Test prepare_messages with no attachments."""
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]
        
        mock_agent = Mock()
        result = handler.prepare_messages(mock_agent, messages, None)
        assert result == messages

    def test_prepare_messages_with_supported_attachments(self):
        """Test prepare_messages with supported attachments."""
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]
        attachments = [{"mime_type": "image/png", "path": "/test.png"}]
        
        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]
        mock_agent.llm.prepare_messages_with_attachments.return_value = messages
        
        result = handler.prepare_messages(mock_agent, messages, attachments)
        mock_agent.llm.prepare_messages_with_attachments.assert_called_once_with(
            messages, attachments
        )
        assert result == messages

    @patch('application.llm.handlers.base.logger')
    def test_prepare_messages_with_unsupported_attachments(self, mock_logger):
        """Test prepare_messages with unsupported attachments."""
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]
        attachments = [{"mime_type": "text/plain", "path": "/test.txt"}]
        
        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]
        
        with patch.object(handler, '_append_unsupported_attachments', return_value=messages) as mock_append:
            result = handler.prepare_messages(mock_agent, messages, attachments)
            mock_append.assert_called_once_with(messages, attachments)
            assert result == messages

    def test_prepare_messages_mixed_attachments(self):
        """Test prepare_messages with both supported and unsupported attachments."""
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]
        attachments = [
            {"mime_type": "image/png", "path": "/test.png"},
            {"mime_type": "text/plain", "path": "/test.txt"}
        ]
        
        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]
        mock_agent.llm.prepare_messages_with_attachments.return_value = messages
        
        with patch.object(handler, '_append_unsupported_attachments', return_value=messages) as mock_append:
            result = handler.prepare_messages(mock_agent, messages, attachments)
            
            # Should call both methods
            mock_agent.llm.prepare_messages_with_attachments.assert_called_once()
            mock_append.assert_called_once()
            assert result == messages

    def test_process_message_flow_non_streaming(self):
        """Test process_message_flow for non-streaming."""
        handler = ConcreteHandler()
        mock_agent = Mock()
        initial_response = "test response"
        tools_dict = {}
        messages = [{"role": "user", "content": "Hello"}]
        
        with patch.object(handler, 'prepare_messages', return_value=messages) as mock_prepare:
            with patch.object(handler, 'handle_non_streaming', return_value="final") as mock_handle:
                result = handler.process_message_flow(
                    mock_agent, initial_response, tools_dict, messages, stream=False
                )
                
                mock_prepare.assert_called_once_with(mock_agent, messages, None)
                mock_handle.assert_called_once_with(mock_agent, initial_response, tools_dict, messages)
                assert result == "final"

    def test_process_message_flow_streaming(self):
        """Test process_message_flow for streaming."""
        handler = ConcreteHandler()
        mock_agent = Mock()
        initial_response = "test response"
        tools_dict = {}
        messages = [{"role": "user", "content": "Hello"}]
        
        def mock_generator():
            yield "chunk1"
            yield "chunk2"
        
        with patch.object(handler, 'prepare_messages', return_value=messages) as mock_prepare:
            with patch.object(handler, 'handle_streaming', return_value=mock_generator()) as mock_handle:
                result = handler.process_message_flow(
                    mock_agent, initial_response, tools_dict, messages, stream=True
                )
                
                mock_prepare.assert_called_once_with(mock_agent, messages, None)
                mock_handle.assert_called_once_with(mock_agent, initial_response, tools_dict, messages)
                
                # Verify it's a generator
                chunks = list(result)
                assert chunks == ["chunk1", "chunk2"]
