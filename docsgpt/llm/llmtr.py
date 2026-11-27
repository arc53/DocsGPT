from docsgpt.core.settings import settings
from docsgpt.llm.openai import OpenAILLM

LLMTR_BASE_URL = "https://llmtr.com/v1"


class LLMTRLLM(OpenAILLM):
    provider_name = "llmtr"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key
            or settings.LLMTR_API_KEY
            or (settings.API_KEY if settings.LLM_PROVIDER == "llmtr" else None),
            user_api_key=user_api_key,
            base_url=base_url or LLMTR_BASE_URL,
            *args,
            **kwargs,
        )
