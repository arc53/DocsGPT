from __future__ import annotations

from typing import Optional

from docsgpt.llm.atlascloud import AtlasCloudLLM
from docsgpt.llm.providers._apikey_or_llm_name import get_api_key
from docsgpt.llm.providers.base import Provider


class AtlasCloudProvider(Provider):
    name = "atlascloud"
    llm_class = AtlasCloudLLM
    api_key_setting = "ATLASCLOUD_API_KEY"

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.ATLASCLOUD_API_KEY)
