from application.core.settings import settings
from application.llm.openai import OpenAILLM

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqLLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.GROQ_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or GROQ_BASE_URL,
            *args,
            **kwargs,
        )
