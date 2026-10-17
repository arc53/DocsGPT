from __future__ import annotations

from typing import Optional

from docsgpt.llm.google_ai import GoogleLLM
from docsgpt.llm.providers._apikey_or_llm_name import get_api_key
from docsgpt.llm.providers.base import Provider


class GoogleProvider(Provider):
    name = "google"
    llm_class = GoogleLLM
    api_key_setting = "GOOGLE_API_KEY"

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.GOOGLE_API_KEY)
