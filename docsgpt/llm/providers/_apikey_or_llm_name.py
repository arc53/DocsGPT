"""Shared helper for providers that follow the
``<X>_API_KEY or (LLM_PROVIDER==X and API_KEY)`` pattern.

This is the dominant pattern across Anthropic, Google, Groq, OpenRouter,
and Novita. Extracted here so each plugin stays a few lines long.

``LLM_NAME`` does not filter these catalogs: it only picks the default
model (see ``resolve_default_model_id``), and the picker keeps listing the
provider's whole catalog.
"""

from __future__ import annotations

from typing import Optional


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
