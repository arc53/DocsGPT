from __future__ import annotations

from typing import Optional

from application.llm.google_ai import GoogleLLM
from application.llm.providers._apikey_or_llm_name import (
    filter_models_by_llm_name,
    get_api_key,
)
from application.llm.providers.base import Provider


class GoogleProvider(Provider):
    name = "google"
    llm_class = GoogleLLM

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.GOOGLE_API_KEY)

    def filter_yaml_models(self, settings, models):
        return filter_models_by_llm_name(
            settings, self.name, settings.GOOGLE_API_KEY, models
        )
