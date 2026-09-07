from __future__ import annotations

from typing import Optional

from docsgpt.llm.anthropic import AnthropicLLM
from docsgpt.llm.providers._apikey_or_llm_name import (
    filter_models_by_llm_name,
    get_api_key,
)
from docsgpt.llm.providers.base import Provider


class AnthropicProvider(Provider):
    name = "anthropic"
    llm_class = AnthropicLLM

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.ANTHROPIC_API_KEY)

    def filter_yaml_models(self, settings, models):
        return filter_models_by_llm_name(
            settings, self.name, settings.ANTHROPIC_API_KEY, models
        )
