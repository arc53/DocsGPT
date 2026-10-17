from __future__ import annotations

from typing import Optional

from docsgpt.llm.openai import OpenAILLM
from docsgpt.llm.providers.base import Provider


class OpenAIProvider(Provider):
    name = "openai"
    llm_class = OpenAILLM
    api_key_setting = "OPENAI_API_KEY"

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
        # Same key rule as ``get_api_key``: ``OPENAI_API_KEY``, or the
        # generic ``API_KEY`` when ``LLM_PROVIDER=openai``. Requiring
        # ``OPENAI_API_KEY`` here left an ``API_KEY``-only setup with no
        # OpenAI model, so it silently defaulted to the hosted DocsGPT API.
        if not self.get_api_key(settings):
            return []
        return models
