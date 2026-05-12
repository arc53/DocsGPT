"""Provider plugin registry.

Plugins are imported eagerly so import errors surface at app boot rather
than at first request. ``ALL_PROVIDERS`` is the canonical ordered list;
``PROVIDERS_BY_NAME`` is a name-keyed lookup for LLMCreator and the
model registry.
"""

from __future__ import annotations

from typing import Dict, List

from application.llm.providers.anthropic import AnthropicProvider
from application.llm.providers.azure_openai import AzureOpenAIProvider
from application.llm.providers.base import Provider
from application.llm.providers.docsgpt import DocsGPTProvider
from application.llm.providers.google import GoogleProvider
from application.llm.providers.groq import GroqProvider
from application.llm.providers.huggingface import HuggingFaceProvider
from application.llm.providers.litellm import LiteLLMProvider
from application.llm.providers.llama_cpp import LlamaCppProvider
from application.llm.providers.novita import NovitaProvider
from application.llm.providers.openai import OpenAIProvider
from application.llm.providers.openai_compatible import OpenAICompatibleProvider
from application.llm.providers.openrouter import OpenRouterProvider
from application.llm.providers.premai import PremAIProvider
from application.llm.providers.sagemaker import SagemakerProvider

# Order here is the order the registry iterates providers (and therefore
# the order ``/api/models`` reports them). Match the historical order
# from the old ModelRegistry._load_models for byte-stable output during
# the migration. ``openai_compatible`` slots in right after ``openai``
# so legacy ``OPENAI_BASE_URL`` models keep landing in the same place.
ALL_PROVIDERS: List[Provider] = [
    DocsGPTProvider(),
    OpenAIProvider(),
    OpenAICompatibleProvider(),
    AzureOpenAIProvider(),
    AnthropicProvider(),
    GoogleProvider(),
    GroqProvider(),
    OpenRouterProvider(),
    NovitaProvider(),
    HuggingFaceProvider(),
    LiteLLMProvider(),
    LlamaCppProvider(),
    PremAIProvider(),
    SagemakerProvider(),
]

PROVIDERS_BY_NAME: Dict[str, Provider] = {p.name: p for p in ALL_PROVIDERS}

__all__ = ["ALL_PROVIDERS", "PROVIDERS_BY_NAME", "Provider"]
