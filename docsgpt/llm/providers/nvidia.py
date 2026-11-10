from __future__ import annotations

from typing import Optional

from docsgpt.llm.nvidia import NvidiaLLM
from docsgpt.llm.providers._apikey_or_llm_name import get_api_key
from docsgpt.llm.providers.base import Provider


class NvidiaProvider(Provider):
    name = "nvidia"
    llm_class = NvidiaLLM
    api_key_setting = "NVIDIA_API_KEY"

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.NVIDIA_API_KEY)
