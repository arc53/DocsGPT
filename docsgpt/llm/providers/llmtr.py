from __future__ import annotations

from typing import Optional

from docsgpt.llm.llmtr import LLMTRLLM
from docsgpt.llm.providers._apikey_or_llm_name import get_api_key
from docsgpt.llm.providers.base import Provider


class LLMTRProvider(Provider):
    name = "llmtr"
    llm_class = LLMTRLLM
    api_key_setting = "LLMTR_API_KEY"

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.LLMTR_API_KEY)
