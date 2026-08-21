from application.core.settings import settings
from application.llm.openai import OpenAILLM

ORCAROUTER_BASE_URL = "https://api.orcarouter.ai/v1"


class OrcaRouterLLM(OpenAILLM):
    provider_name = "orcarouter"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.ORCAROUTER_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or ORCAROUTER_BASE_URL,
            *args,
            **kwargs,
        )
