from __future__ import annotations

from typing import Optional

from application.llm.docsgpt_provider import DocsGPTAPILLM
from application.llm.providers.base import Provider


class DocsGPTProvider(Provider):
    name = "docsgpt"
    llm_class = DocsGPTAPILLM

    def get_api_key(self, settings) -> Optional[str]:
        # No provider-specific key; the LLM class can use the generic
        # API_KEY fallback if it needs one. Mirrors model_utils' historical
        # behavior of returning settings.API_KEY when no specific key exists.
        return settings.API_KEY

    def is_enabled(self, settings) -> bool:
        # The hosted DocsGPT model is hidden when the deployment is
        # pointed at a custom OpenAI-compatible endpoint.
        return not settings.OPENAI_BASE_URL
