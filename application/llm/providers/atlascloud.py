from __future__ import annotations

from typing import Optional

from application.llm.atlascloud import AtlasCloudLLM
from application.llm.providers._apikey_or_llm_name import (
    filter_models_by_llm_name,
    get_api_key,
)
from application.llm.providers.base import Provider


class AtlasCloudProvider(Provider):
    name = "atlascloud"
    llm_class = AtlasCloudLLM

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.ATLASCLOUD_API_KEY)

    def filter_yaml_models(self, settings, models):
        return filter_models_by_llm_name(
            settings, self.name, settings.ATLASCLOUD_API_KEY, models
        )
