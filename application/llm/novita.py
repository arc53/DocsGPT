from application.core.settings import settings
from application.llm.openai import OpenAILLM

NOVITA_BASE_URL = "https://api.novita.ai/v3/openai"


class NovitaLLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or NOVITA_BASE_URL,
            *args,
            **kwargs,
        )
