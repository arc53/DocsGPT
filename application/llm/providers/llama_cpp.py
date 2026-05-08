from __future__ import annotations

from typing import Optional

from application.llm.llama_cpp import LlamaCpp
from application.llm.providers.base import Provider


class LlamaCppProvider(Provider):
    """LLMCreator-only plugin: invocable via LLM_PROVIDER but not in the catalog."""

    name = "llama.cpp"
    llm_class = LlamaCpp

    def get_api_key(self, settings) -> Optional[str]:
        return settings.API_KEY

    def is_enabled(self, settings) -> bool:
        return False
