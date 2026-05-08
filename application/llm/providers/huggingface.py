from __future__ import annotations

from typing import Optional

from application.llm.providers._apikey_or_llm_name import (
    get_api_key as shared_get_api_key,
)
from application.llm.providers.base import Provider


class HuggingFaceProvider(Provider):
    """Surfaces ``huggingface-local`` to the model catalog.

    Not dispatchable through LLMCreator — historically there was no
    HuggingFaceLLM entry in ``LLMCreator.llms``, and calling ``create_llm``
    with ``"huggingface"`` raised ``ValueError``. We preserve that
    behavior: the model appears in ``/api/models`` but selecting it
    surfaces the same error it always did.
    """

    name = "huggingface"
    llm_class = None  # not dispatchable

    def get_api_key(self, settings) -> Optional[str]:
        return shared_get_api_key(settings, self.name, settings.HUGGINGFACE_API_KEY)
