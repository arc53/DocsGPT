from __future__ import annotations

from typing import Optional

from docsgpt.llm.groq import GroqLLM
from docsgpt.llm.providers._apikey_or_llm_name import get_api_key
from docsgpt.llm.providers.base import Provider


class GroqProvider(Provider):
    name = "groq"
    llm_class = GroqLLM
    api_key_setting = "GROQ_API_KEY"

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.GROQ_API_KEY)
