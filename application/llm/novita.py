from application.core.settings import settings
from application.llm.openai import OpenAILLM

NOVITA_BASE_URL = "https://api.novita.ai/openai"


class NovitaLLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.NOVITA_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or NOVITA_BASE_URL,
            *args,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Astraflow (UCloud ModelVerse) provider
# ---------------------------------------------------------------------------

ASTRAFLOW_BASE_URL = "https://api.astraflow.com/v1"
ASTRAFLOW_CN_BASE_URL = "https://api.modelverse.cn/v1"


class AstraflowLLM(OpenAILLM):
    """Astraflow (UCloud ModelVerse) – global endpoint."""

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.ASTRAFLOW_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or ASTRAFLOW_BASE_URL,
            *args,
            **kwargs,
        )


class AstraflowCNLLM(OpenAILLM):
    """Astraflow (UCloud ModelVerse) – China-region endpoint."""

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.ASTRAFLOW_CN_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or ASTRAFLOW_CN_BASE_URL,
            *args,
            **kwargs,
        )
