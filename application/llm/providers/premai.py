from __future__ import annotations

from typing import Optional

from application.llm.premai import PremAILLM
from application.llm.providers.base import Provider


class PremAIProvider(Provider):
    """LLMCreator-only plugin: invocable via LLM_PROVIDER but not in the catalog."""

    name = "premai"
    llm_class = PremAILLM

    def get_api_key(self, settings) -> Optional[str]:
        return settings.API_KEY

    def is_enabled(self, settings) -> bool:
        return False
