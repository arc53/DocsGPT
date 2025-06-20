from application.llm.handlers.base import LLMHandler
from application.llm.handlers.google import GoogleLLMHandler
from application.llm.handlers.openai import OpenAILLMHandler


class LLMHandlerCreator:
    handlers = {
        "openai": OpenAILLMHandler,
        "google": GoogleLLMHandler,
        "default": OpenAILLMHandler,
    }

    @classmethod
    def create_handler(cls, llm_type: str, *args, **kwargs) -> LLMHandler:
        handler_class = cls.handlers.get(llm_type.lower())
        if not handler_class:
            handler_class = OpenAILLMHandler
        return handler_class(*args, **kwargs)
