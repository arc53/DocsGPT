from __future__ import annotations

from typing import Optional

from application.llm.sagemaker import SagemakerAPILLM
from application.llm.providers.base import Provider


class SagemakerProvider(Provider):
    """LLMCreator-only plugin: invocable via LLM_PROVIDER but not in the catalog.

    SageMaker reads its credentials from ``SAGEMAKER_*`` settings inside
    the LLM class itself; this plugin's ``get_api_key`` exists only for
    LLMCreator's symmetry.
    """

    name = "sagemaker"
    llm_class = SagemakerAPILLM

    def get_api_key(self, settings) -> Optional[str]:
        return settings.API_KEY

    def is_enabled(self, settings) -> bool:
        return False
