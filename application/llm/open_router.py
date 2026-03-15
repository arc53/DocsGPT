from application.core.settings import settings
from application.llm.openai import OpenAILLM

OPEN_ROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterLLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.OPEN_ROUTER_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or OPEN_ROUTER_BASE_URL,
            *args,
            **kwargs,
        )
