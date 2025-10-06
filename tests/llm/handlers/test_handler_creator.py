
from application.llm.handlers.handler_creator import LLMHandlerCreator
from application.llm.handlers.base import LLMHandler
from application.llm.handlers.openai import OpenAILLMHandler
from application.llm.handlers.google import GoogleLLMHandler


class TestLLMHandlerCreator:
    """Test LLMHandlerCreator class."""

    def test_create_openai_handler(self):
        """Test creating OpenAI handler."""
        handler = LLMHandlerCreator.create_handler("openai")
        
        assert isinstance(handler, OpenAILLMHandler)
        assert isinstance(handler, LLMHandler)

    def test_create_openai_handler_case_insensitive(self):
        """Test creating OpenAI handler with different cases."""
        handler_upper = LLMHandlerCreator.create_handler("OPENAI")
        handler_mixed = LLMHandlerCreator.create_handler("OpenAI")
        
        assert isinstance(handler_upper, OpenAILLMHandler)
        assert isinstance(handler_mixed, OpenAILLMHandler)

    def test_create_google_handler(self):
        """Test creating Google handler."""
        handler = LLMHandlerCreator.create_handler("google")
        
        assert isinstance(handler, GoogleLLMHandler)
        assert isinstance(handler, LLMHandler)

    def test_create_google_handler_case_insensitive(self):
        """Test creating Google handler with different cases."""
        handler_upper = LLMHandlerCreator.create_handler("GOOGLE")
        handler_mixed = LLMHandlerCreator.create_handler("Google")

        assert isinstance(handler_upper, GoogleLLMHandler)
        assert isinstance(handler_mixed, GoogleLLMHandler)



    def test_create_default_handler(self):
        """Test creating default handler."""
        handler = LLMHandlerCreator.create_handler("default")
        
        assert isinstance(handler, OpenAILLMHandler)

    def test_create_unknown_handler_fallback(self):
        """Test creating handler for unknown type falls back to OpenAI."""
        handler = LLMHandlerCreator.create_handler("unknown_provider")

        assert isinstance(handler, OpenAILLMHandler)

    def test_create_anthropic_handler_fallback(self):
        """Test creating Anthropic handler falls back to OpenAI (not supported in handlers)."""
        handler = LLMHandlerCreator.create_handler("anthropic")

        assert isinstance(handler, OpenAILLMHandler)

    def test_create_empty_string_handler_fallback(self):
        """Test creating handler with empty string falls back to OpenAI."""
        handler = LLMHandlerCreator.create_handler("")
        
        assert isinstance(handler, OpenAILLMHandler)



    def test_handlers_registry(self):
        """Test the handlers registry contains expected mappings."""
        expected_handlers = {
            "openai": OpenAILLMHandler,
            "google": GoogleLLMHandler,
            "default": OpenAILLMHandler,
        }

        assert LLMHandlerCreator.handlers == expected_handlers

    def test_create_handler_with_args(self):
        """Test creating handler with additional arguments."""
        handler = LLMHandlerCreator.create_handler("openai")
        
        assert isinstance(handler, OpenAILLMHandler)
        assert handler.llm_calls == []
        assert handler.tool_calls == []

    def test_create_handler_with_kwargs(self):
        """Test creating handler with keyword arguments."""
        handler = LLMHandlerCreator.create_handler("google")
        
        assert isinstance(handler, GoogleLLMHandler)
        assert handler.llm_calls == []
        assert handler.tool_calls == []

    def test_all_registered_handlers_are_valid(self):
        """Test that all registered handlers can be instantiated."""
        for handler_type in LLMHandlerCreator.handlers.keys():
            handler = LLMHandlerCreator.create_handler(handler_type)
            assert isinstance(handler, LLMHandler)
            assert hasattr(handler, 'parse_response')
            assert hasattr(handler, 'create_tool_message')
            assert hasattr(handler, '_iterate_stream')

    def test_handler_inheritance(self):
        """Test that all created handlers inherit from LLMHandler."""
        test_types = ["openai", "google", "default", "unknown"]
        
        for handler_type in test_types:
            handler = LLMHandlerCreator.create_handler(handler_type)
            assert isinstance(handler, LLMHandler)
            
            assert callable(getattr(handler, 'parse_response'))
            assert callable(getattr(handler, 'create_tool_message'))
            assert callable(getattr(handler, '_iterate_stream'))

    def test_create_handler_preserves_handler_state(self):
        """Test that each created handler has independent state."""
        handler1 = LLMHandlerCreator.create_handler("openai")
        handler2 = LLMHandlerCreator.create_handler("openai")
        
        handler1.llm_calls.append("test_call")

        assert len(handler1.llm_calls) == 1
        assert len(handler2.llm_calls) == 0
        assert handler1 is not handler2
