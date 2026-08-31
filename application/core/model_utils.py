from typing import Any, Dict, Optional

from application.core.model_registry import ModelRegistry


def get_api_key_for_provider(provider: str) -> Optional[str]:
    """Get the appropriate API key for a provider.

    Delegates to the provider plugin's ``get_api_key``. Falls back to the
    generic ``settings.API_KEY`` for unknown providers.
    """
    from application.core.settings import settings
    from application.llm.providers import PROVIDERS_BY_NAME

    plugin = PROVIDERS_BY_NAME.get(provider)
    if plugin is not None:
        key = plugin.get_api_key(settings)
        if key:
            return key
    return settings.API_KEY


def resolve_dispatch_provider(
    stored_llm_name: Optional[str],
    model_id: Optional[str] = None,
    user_id: Optional[str] = None,
    fallback: Optional[str] = None,
) -> Optional[str]:
    """Resolve a stored provider string to one ``LLMCreator`` can dispatch.

    ``/api/models`` reports ``display_provider`` when a catalog YAML sets one
    (``foundry``, ``azure_foundry``, ``cloudflare``, …), and clients persist
    that label as ``llm_name`` on agents and workflow nodes. Those labels are
    presentation-only: they are absent from ``PROVIDERS_BY_NAME``, so passing
    one to ``LLMCreator.create_llm`` raises ``No LLM class found for type
    <label>``. Normalizing here keeps already-stored records working without a
    migration.

    Resolution order: a stored name that is a real dispatch provider wins;
    otherwise the model registry decides; otherwise ``fallback``.

    Args:
        stored_llm_name: Provider string persisted on the record, possibly a
            display label.
        model_id: Model whose registry entry knows the true provider.
        user_id: BYOM-resolution scope for per-user model records.
        fallback: Used when neither the stored name nor the registry resolves.

    Returns:
        A dispatchable provider name, or ``fallback`` when nothing resolves.
    """
    from application.llm.providers import PROVIDERS_BY_NAME

    # Return the *canonical* lowercase name. ``LLMCreator`` lowercases before
    # its own lookup, but ``get_api_key_for_provider`` matches exactly — so a
    # stored "OpenAI" would pass this guard and then silently fall through to
    # ``settings.API_KEY``, which is the key leak this function exists to stop.
    if stored_llm_name and stored_llm_name.lower() in PROVIDERS_BY_NAME:
        return stored_llm_name.lower()
    if model_id:
        resolved = get_provider_from_model_id(model_id, user_id=user_id)
        if resolved:
            return resolved
    if fallback and fallback.lower() in PROVIDERS_BY_NAME:
        return fallback.lower()
    return fallback


def get_all_available_models(
    user_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Get all available models with metadata for API response.

    When ``user_id`` is supplied, the user's BYOM custom-model records
    are merged into the result alongside the built-in catalog.
    """
    registry = ModelRegistry.get_instance()
    return {
        model.id: model.to_dict()
        for model in registry.get_enabled_models(user_id=user_id)
    }


def validate_model_id(model_id: str, user_id: Optional[str] = None) -> bool:
    """Check if a model ID exists in registry.

    ``user_id`` enables resolution of per-user BYOM records (UUIDs).
    Without it, only built-in catalog ids resolve.
    """
    registry = ModelRegistry.get_instance()
    return registry.model_exists(model_id, user_id=user_id)


def get_model_capabilities(
    model_id: str, user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get capabilities for a specific model.

    ``user_id`` enables resolution of per-user BYOM records.
    """
    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id, user_id=user_id)
    if model:
        return {
            "supported_attachment_types": model.capabilities.supported_attachment_types,
            "supports_tools": model.capabilities.supports_tools,
            "supports_structured_output": model.capabilities.supports_structured_output,
            "context_window": model.capabilities.context_window,
        }
    return None


def get_default_model_id() -> str:
    """Get the system default model ID"""
    registry = ModelRegistry.get_instance()
    return registry.default_model_id


def get_provider_from_model_id(
    model_id: str, user_id: Optional[str] = None
) -> Optional[str]:
    """Get the provider name for a given model_id.

    ``user_id`` enables resolution of per-user BYOM records (UUIDs).
    Without it, BYOM model ids return ``None`` and the caller falls
    back to the deployment default.
    """
    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id, user_id=user_id)
    if model:
        return model.provider.value
    return None


def get_token_limit(model_id: str, user_id: Optional[str] = None) -> int:
    """Get context window (token limit) for a model.

    Returns the model's ``context_window`` or ``DEFAULT_LLM_TOKEN_LIMIT``
    if not found. ``user_id`` enables resolution of per-user BYOM records.
    """
    from application.core.settings import settings

    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id, user_id=user_id)
    if model:
        return model.capabilities.context_window
    return settings.DEFAULT_LLM_TOKEN_LIMIT


def get_base_url_for_model(
    model_id: str, user_id: Optional[str] = None
) -> Optional[str]:
    """Get the custom base_url for a specific model if configured.

    Returns ``None`` if no custom base_url is set. ``user_id`` enables
    resolution of per-user BYOM records.
    """
    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id, user_id=user_id)
    if model:
        return model.base_url
    return None


def get_api_key_for_model(
    model_id: str, user_id: Optional[str] = None
) -> Optional[str]:
    """Resolve the API key to use when invoking ``model_id``.

    Priority:
      1. The model record's own ``api_key`` (BYOM records and
         ``openai_compatible`` YAMLs populate this).
      2. The provider plugin's settings-based key.

    ``user_id`` enables resolution of per-user BYOM records.
    """
    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id, user_id=user_id)
    if model is not None and model.api_key:
        return model.api_key
    if model is not None:
        return get_api_key_for_provider(model.provider.value)
    return None
