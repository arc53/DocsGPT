from docsgpt.llm.handlers.anthropic import AnthropicLLMHandler
from docsgpt.llm.handlers.base import LLMHandler
from docsgpt.llm.handlers.google import GoogleLLMHandler
from docsgpt.llm.handlers.openai import OpenAILLMHandler


class LLMHandlerCreator:
    handlers = {
        "openai": OpenAILLMHandler,
        "google": GoogleLLMHandler,
        "anthropic": AnthropicLLMHandler,
        "novita": OpenAILLMHandler,  # Novita uses OpenAI-compatible API
        "default": OpenAILLMHandler,
    }

    @classmethod
    def create_handler(cls, llm_type: str, *args, **kwargs) -> LLMHandler:
        handler_class = cls.handlers.get(llm_type.lower())
        if not handler_class:
            handler_class = OpenAILLMHandler
        return handler_class(*args, **kwargs)
