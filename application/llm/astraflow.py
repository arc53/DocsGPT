from application.core.settings import settings
from application.llm.openai import OpenAILLM

ASTRAFLOW_BASE_URL = "https://api-us-ca.umodelverse.ai/v1"
ASTRAFLOW_CN_BASE_URL = "https://api.modelverse.cn/v1"


class AstraflowLLM(OpenAILLM):
    """Astraflow global endpoint (OpenAI-compatible)."""

    provider_name = "astraflow"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.ASTRAFLOW_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or ASTRAFLOW_BASE_URL,
            *args,
            **kwargs,
        )


class AstraflowCNLLM(OpenAILLM):
    """Astraflow China endpoint (OpenAI-compatible)."""

    provider_name = "astraflow_cn"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.ASTRAFLOW_CN_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or ASTRAFLOW_CN_BASE_URL,
            *args,
            **kwargs,
        )
