from __future__ import annotations

from typing import Optional

from application.llm.astraflow import AstraflowCNLLM, AstraflowLLM
from application.llm.providers._apikey_or_llm_name import (
    filter_models_by_llm_name,
    get_api_key,
)
from application.llm.providers.base import Provider


class AstraflowProvider(Provider):
    """Astraflow global endpoint — OpenAI-compatible, 200+ models."""

    name = "astraflow"
    llm_class = AstraflowLLM

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.ASTRAFLOW_API_KEY)

    def filter_yaml_models(self, settings, models):
        return filter_models_by_llm_name(
            settings, self.name, settings.ASTRAFLOW_API_KEY, models
        )


class AstraflowCNProvider(Provider):
    """Astraflow China endpoint — OpenAI-compatible, 200+ models."""

    name = "astraflow_cn"
    llm_class = AstraflowCNLLM

    def get_api_key(self, settings) -> Optional[str]:
        return get_api_key(settings, self.name, settings.ASTRAFLOW_CN_API_KEY)

    def filter_yaml_models(self, settings, models):
        return filter_models_by_llm_name(
            settings, self.name, settings.ASTRAFLOW_CN_API_KEY, models
        )
