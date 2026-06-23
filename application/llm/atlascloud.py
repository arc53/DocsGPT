from application.core.settings import settings
from application.llm.openai import OpenAILLM

ATLASCLOUD_BASE_URL = "https://api.atlascloud.ai/v1"


class AtlasCloudLLM(OpenAILLM):
    provider_name = "atlascloud"

    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.ATLASCLOUD_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or ATLASCLOUD_BASE_URL,
            *args,
            **kwargs,
        )
