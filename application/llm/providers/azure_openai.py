from __future__ import annotations

from typing import Optional

from application.llm.openai import AzureOpenAILLM
from application.llm.providers.base import Provider


class AzureOpenAIProvider(Provider):
    name = "azure_openai"
    llm_class = AzureOpenAILLM

    def get_api_key(self, settings) -> Optional[str]:
        # Azure historically uses the generic API_KEY field.
        return settings.API_KEY

    def is_enabled(self, settings) -> bool:
        if settings.OPENAI_API_BASE:
            return True
        return settings.LLM_PROVIDER == self.name and bool(settings.API_KEY)

    def filter_yaml_models(self, settings, models):
        # Mirrors _add_azure_openai_models: when LLM_PROVIDER==azure_openai
        # and LLM_NAME matches a known model, narrow to that one model.
        # Otherwise load the entire catalog.
        if settings.LLM_PROVIDER == self.name and settings.LLM_NAME:
            named = [m for m in models if m.id == settings.LLM_NAME]
            if named:
                return named
        return models
