from application.core.settings import settings
from application.llm.openai import OpenAILLM

MODELSLAB_BASE_URL = "https://modelslab.com/api/uncensored-chat/v1"


class ModelsLabLLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.MODELSLAB_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or MODELSLAB_BASE_URL,
            *args,
            **kwargs,
        )
