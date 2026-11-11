from docsgpt.core.settings import settings
from docsgpt.llm.openai import OpenAILLM

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NvidiaLLM(OpenAILLM):
    provider_name = "nvidia"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key
            or settings.NVIDIA_API_KEY
            or (settings.API_KEY if settings.LLM_PROVIDER == "nvidia" else None),
            user_api_key=user_api_key,
            base_url=base_url or NVIDIA_BASE_URL,
            *args,
            **kwargs,
        )
