from __future__ import annotations

from typing import Optional

from application.llm.openai import OpenAILLM
from application.llm.providers.base import Provider


class OpenAIProvider(Provider):
    name = "openai"
    llm_class = OpenAILLM

    def get_api_key(self, settings) -> Optional[str]:
        if settings.OPENAI_API_KEY:
            return settings.OPENAI_API_KEY
        if settings.LLM_PROVIDER == self.name and settings.API_KEY:
            return settings.API_KEY
        return None

    def is_enabled(self, settings) -> bool:
        # When the deployment is pointed at a custom OpenAI-compatible
        # endpoint (Ollama, LM Studio, ...), the cloud-OpenAI catalog is
        # suppressed but ``is_enabled`` stays True — necessary so the
        # filter below still gets to drop the catalog (rather than the
        # registry skipping the provider entirely and missing the rule).
        if settings.OPENAI_BASE_URL:
            return True
        return bool(self.get_api_key(settings))

    def filter_yaml_models(self, settings, models):
        # Legacy local-endpoint mode hides the cloud catalog. The
        # corresponding dynamic models live in OpenAICompatibleProvider.
        if settings.OPENAI_BASE_URL:
            return []
        if not settings.OPENAI_API_KEY:
            return []
        return models
