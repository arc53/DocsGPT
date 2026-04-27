"""Shared helper for providers that follow the
``<X>_API_KEY or (LLM_PROVIDER==X and API_KEY)`` pattern.

This is the dominant pattern across Anthropic, Google, Groq, OpenRouter,
and Novita. Extracted here so each plugin stays a few lines long.
"""

from __future__ import annotations

from typing import List, Optional

from application.core.model_settings import AvailableModel


def get_api_key(
    settings,
    provider_name: str,
    provider_specific_key: Optional[str],
) -> Optional[str]:
    if provider_specific_key:
        return provider_specific_key
    if settings.LLM_PROVIDER == provider_name and settings.API_KEY:
        return settings.API_KEY
    return None


def filter_models_by_llm_name(
    settings,
    provider_name: str,
    provider_specific_key: Optional[str],
    models: List[AvailableModel],
) -> List[AvailableModel]:
    """Mirrors the historical ``_add_<X>_models`` selection logic.

    Behavior:
    - If the provider-specific API key is set → load all models.
    - Else if ``LLM_PROVIDER`` matches and ``LLM_NAME`` matches a known
      model → load just that model.
    - Otherwise → load all models (preserved "load anyway" branch from
      the original methods).
    """
    if provider_specific_key:
        return models
    if (
        settings.LLM_PROVIDER == provider_name
        and settings.LLM_NAME
    ):
        named = [m for m in models if m.id == settings.LLM_NAME]
        if named:
            return named
    return models
