import pytest
from unittest.mock import Mock, patch

from application.agents.base import BaseAgent
from application.llm.handlers.base import LLMHandler, ToolCall


class MockAgent(BaseAgent):
    """Mock agent for testing"""

    def _gen_inner(self, query, log_context=None):
        yield {"answer": "test"}


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing"""
    agent = MockAgent(
        endpoint="test",
        llm_name="openai",
        model_id="gpt-4o",
        api_key="test-key",
    )
    agent.llm = Mock()
    return agent


@pytest.fixture
def mock_llm_handler():
    """Create a mock LLM handler"""
    handler = Mock(spec=LLMHandler)
    handler.tool_calls = []
    return handler


class TestAgentTokenTracking:
    """Test suite for agent token tracking during execution"""

    def test_calculate_current_context_tokens(self, mock_agent):
        """Test token calculation for current context"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
        ]

        tokens = mock_agent._calculate_current_context_tokens(messages)

        # Should count tokens from all messages
        assert tokens > 0
        # Rough estimate: ~20-40 tokens for this conversation
        assert 15 < tokens < 60

    def test_calculate_tokens_with_tool_calls(self, mock_agent):
        """Test token calculation includes tool call content"""
        messages = [
            {"role": "system", "content": "Test"},
            {
                "role": "assistant",
                "content": [
                    {
                        "function_call": {
                            "name": "search_tool",
                            "args": {"query": "test"},
                            "call_id": "123",
                        }
                    }
                ],
            },
            {
                "role": "tool",
                "content": [
                    {
                        "function_response": {
                            "name": "search_tool",
                            "response": {"result": "Found 10 results"},
                            "call_id": "123",
                        }
                    }
                ],
            },
        ]

        tokens = mock_agent._calculate_current_context_tokens(messages)

        # Should include tool call tokens
        assert tokens > 0

    @patch("application.core.model_utils.get_token_limit")
    @patch("application.core.settings.settings")
    def test_check_context_limit_below_threshold(
        self, mock_settings, mock_get_token_limit, mock_agent
    ):
        """Test context limit check when below threshold"""
        mock_get_token_limit.return_value = 128000
        mock_settings.COMPRESSION_THRESHOLD_PERCENTAGE = 0.8

        messages = [
            {"role": "system", "content": "Short message"},
            {"role": "user", "content": "Hello"},
        ]

        # Should return False for small conversation
        result = mock_agent._check_context_limit(messages)
        assert result is False

        # Should track current token count
        assert mock_agent.current_token_count > 0
        assert mock_agent.current_token_count < 128000 * 0.8

    @patch("application.core.model_utils.get_token_limit")
    @patch("application.core.settings.settings")
    def test_check_context_limit_above_threshold(
        self, mock_settings, mock_get_token_limit, mock_agent
    ):
        """Test context limit check when above threshold"""
        mock_get_token_limit.return_value = 100  # Very small limit for testing
        mock_settings.COMPRESSION_THRESHOLD_PERCENTAGE = 0.8

        # Create messages that will exceed 80 tokens (80% of 100)
        messages = [
            {"role": "system", "content": "a " * 50},  # ~50 tokens
            {"role": "user", "content": "b " * 50},  # ~50 tokens
        ]

        # Should return True when exceeding threshold
        result = mock_agent._check_context_limit(messages)
        assert result is True

    @patch("application.agents.base.logger")
    def test_check_context_limit_error_handling(self, mock_logger, mock_agent):
        """Test error handling in context limit check"""
        # Force an error by making get_token_limit fail
        with patch(
            "application.core.model_utils.get_token_limit", side_effect=Exception("Test error")
        ):
            messages = [{"role": "user", "content": "test"}]

            result = mock_agent._check_context_limit(messages)

            # Should return False on error (safe default)
            assert result is False
            # Should log the error
            assert mock_logger.error.called

    def test_context_limit_flag_initialization(self, mock_agent):
        """Test that context limit flag is initialized"""
        assert hasattr(mock_agent, "context_limit_reached")
        assert mock_agent.context_limit_reached is False

        assert hasattr(mock_agent, "current_token_count")
        assert mock_agent.current_token_count == 0


class TestLLMHandlerTokenTracking:
    """Test suite for LLM handler token tracking"""

    @patch("application.llm.handlers.base.logger")
    def test_handle_tool_calls_stops_at_limit(self, mock_logger):
        """Test that tool execution stops when context limit is reached"""
        from application.llm.handlers.base import LLMHandler

        # Create a concrete handler for testing
        class TestHandler(LLMHandler):
            def parse_response(self, response):
                pass

            def create_tool_message(self, tool_call, result):
                return {"role": "tool", "content": str(result)}

            def _iterate_stream(self, response):
                yield ""

        handler = TestHandler()

        # Create mock agent that hits limit on second tool
        mock_agent = Mock()
        mock_agent.context_limit_reached = False

        call_count = [0]

        def check_limit_side_effect(messages):
            call_count[0] += 1
            # Return True on second call (second tool)
            return call_count[0] >= 2

        mock_agent._check_context_limit = Mock(side_effect=check_limit_side_effect)
        mock_agent._execute_tool_action = Mock(
            return_value=iter([{"type": "tool_call", "data": {}}])
        )

        # Create multiple tool calls
        tool_calls = [
            ToolCall(id="1", name="tool1", arguments={}),
            ToolCall(id="2", name="tool2", arguments={}),
            ToolCall(id="3", name="tool3", arguments={}),
        ]

        messages = []
        tools_dict = {}

        # Execute tool calls
        results = list(handler.handle_tool_calls(mock_agent, tool_calls, tools_dict, messages))

        # First tool should execute
        assert mock_agent._execute_tool_action.call_count == 1

        # Should have yielded skip messages for tools 2 and 3
        skip_messages = [r for r in results if r.get("type") == "tool_call" and r.get("data", {}).get("status") == "skipped"]
        assert len(skip_messages) == 2

        # Should have set the flag
        assert mock_agent.context_limit_reached is True

        # Should have logged warning
        assert mock_logger.warning.called

    def test_handle_tool_calls_all_execute_when_no_limit(self):
        """Test that all tools execute when under limit"""
        from application.llm.handlers.base import LLMHandler

        class TestHandler(LLMHandler):
            def parse_response(self, response):
                pass

            def create_tool_message(self, tool_call, result):
                return {"role": "tool", "content": str(result)}

            def _iterate_stream(self, response):
                yield ""

        handler = TestHandler()

        # Create mock agent that never hits limit
        mock_agent = Mock()
        mock_agent.context_limit_reached = False
        mock_agent._check_context_limit = Mock(return_value=False)
        mock_agent._execute_tool_action = Mock(
            return_value=iter([{"type": "tool_call", "data": {}}])
        )

        tool_calls = [
            ToolCall(id="1", name="tool1", arguments={}),
            ToolCall(id="2", name="tool2", arguments={}),
            ToolCall(id="3", name="tool3", arguments={}),
        ]

        messages = []
        tools_dict = {}

        # Execute tool calls
        list(handler.handle_tool_calls(mock_agent, tool_calls, tools_dict, messages))

        # All 3 tools should execute
        assert mock_agent._execute_tool_action.call_count == 3

        # Should not have set the flag
        assert mock_agent.context_limit_reached is False

    @patch("application.llm.handlers.base.logger")
    def test_handle_streaming_adds_warning_message(self, mock_logger):
        """Test that streaming handler adds warning when limit reached"""
        from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall

        class TestHandler(LLMHandler):
            def parse_response(self, response):
                if isinstance(response, dict) and response.get("type") == "tool_call":
                    return LLMResponse(
                        content="",
                        tool_calls=[ToolCall(id="1", name="test", arguments={}, index=0)],
                        finish_reason="tool_calls",
                        raw_response=None,
                    )
                else:
                    return LLMResponse(
                        content="Done",
                        tool_calls=[],
                        finish_reason="stop",
                        raw_response=None,
                    )

            def create_tool_message(self, tool_call, result):
                return {"role": "tool", "content": str(result)}

            def _iterate_stream(self, response):
                if response == "first":
                    yield {"type": "tool_call"}  # Object to be parsed, not string
                else:
                    yield {"type": "stop"}  # Object to be parsed, not string

        handler = TestHandler()

        # Create mock agent with limit reached
        mock_agent = Mock()
        mock_agent.context_limit_reached = True
        mock_agent.model_id = "gpt-4o"
        mock_agent.tools = []
        mock_agent.llm = Mock()
        mock_agent.llm.gen_stream = Mock(return_value="second")

        def tool_handler_gen(*args):
            yield {"type": "tool", "data": {}}
            return []

        # Mock handle_tool_calls to return messages and set flag
        with patch.object(
            handler, "handle_tool_calls", return_value=tool_handler_gen()
        ):
            messages = []
            tools_dict = {}

            # Execute streaming
            list(handler.handle_streaming(mock_agent, "first", tools_dict, messages))

            # Should have called gen_stream with tools=None (disabled)
            mock_agent.llm.gen_stream.assert_called()
            call_kwargs = mock_agent.llm.gen_stream.call_args.kwargs
            assert call_kwargs.get("tools") is None

            # Should have logged the warning
            assert mock_logger.info.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
