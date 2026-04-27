from __future__ import annotations

from typing import Optional

from application.llm.novita import NovitaLLM
from application.llm.providers._apikey_or_llm_name import (
    filter_models_by_llm_name,
    get_api_key,
)
from application.llm.providers.base import Provider


class NovitaProvider(Provider):
    name = "novita"
    llm_class = NovitaLLM

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.NOVITA_API_KEY)

    def filter_yaml_models(self, settings, models):
        return filter_models_by_llm_name(
            settings, self.name, settings.NOVITA_API_KEY, models
        )
