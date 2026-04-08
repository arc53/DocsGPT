from application.core.settings import settings
from application.llm.openai import OpenAILLM

QIANFAN_BASE_URL = "https://qianfan.baidubce.com/v2"


class QianfanLLM(OpenAILLM):
    def __init__(self, api_key=None, user_api_key=None, base_url=None, *args, **kwargs):
        super().__init__(
            api_key=api_key or settings.QIANFAN_API_KEY or settings.API_KEY,
            user_api_key=user_api_key,
            base_url=base_url or QIANFAN_BASE_URL,
            *args,
            **kwargs,
        )

    def get_supported_attachment_types(self):
        """Keep the first Qianfan integration text-only until attachment support is verified."""
        return []

    def _supports_tools(self):
        """Disable tools until Qianfan tool-calling is verified end-to-end."""
        return False

    def _supports_structured_output(self):
        """Disable structured output until JSON schema support is verified end-to-end."""
        return False
