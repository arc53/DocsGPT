"""Provider plugin registry.

Plugins are imported eagerly so import errors surface at app boot rather
than at first request. ``ALL_PROVIDERS`` is the canonical ordered list;
``PROVIDERS_BY_NAME`` is a name-keyed lookup for LLMCreator and the
model registry.
"""

from __future__ import annotations

from typing import Dict, List

from docsgpt.llm.providers.anthropic import AnthropicProvider
from docsgpt.llm.providers.base import Provider
from docsgpt.llm.providers.docsgpt import DocsGPTProvider
from docsgpt.llm.providers.google import GoogleProvider
from docsgpt.llm.providers.groq import GroqProvider
from docsgpt.llm.providers.huggingface import HuggingFaceProvider
from docsgpt.llm.providers.llama_cpp import LlamaCppProvider
from docsgpt.llm.providers.novita import NovitaProvider
from docsgpt.llm.providers.openai import OpenAIProvider
from docsgpt.llm.providers.openai_compatible import OpenAICompatibleProvider
from docsgpt.llm.providers.openrouter import OpenRouterProvider

# Order here is the order the registry iterates providers (and therefore
# the order ``/api/models`` reports them). Match the historical order
# from the old ModelRegistry._load_models for byte-stable output during
# the migration. ``openai_compatible`` slots in right after ``openai``
# so legacy ``OPENAI_BASE_URL`` models keep landing in the same place.
ALL_PROVIDERS: List[Provider] = [
    DocsGPTProvider(),
    OpenAIProvider(),
    OpenAICompatibleProvider(),
    AnthropicProvider(),
    GoogleProvider(),
    GroqProvider(),
    OpenRouterProvider(),
    NovitaProvider(),
    HuggingFaceProvider(),
    LlamaCppProvider(),
]

PROVIDERS_BY_NAME: Dict[str, Provider] = {p.name: p for p in ALL_PROVIDERS}

__all__ = ["ALL_PROVIDERS", "PROVIDERS_BY_NAME", "Provider"]
