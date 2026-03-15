from typing import Any, Dict, Optional

from application.core.model_settings import ModelRegistry


def get_api_key_for_provider(provider: str) -> Optional[str]:
    """Get the appropriate API key for a provider"""
    from application.core.settings import settings

    provider_key_map = {
        "openai": settings.OPENAI_API_KEY,
        "openrouter": settings.OPEN_ROUTER_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
        "google": settings.GOOGLE_API_KEY,
        "groq": settings.GROQ_API_KEY,
        "huggingface": settings.HUGGINGFACE_API_KEY,
        "azure_openai": settings.API_KEY,
        "docsgpt": None,
        "llama.cpp": None,
    }

    provider_key = provider_key_map.get(provider)
    if provider_key:
        return provider_key
    return settings.API_KEY


def get_all_available_models() -> Dict[str, Dict[str, Any]]:
    """Get all available models with metadata for API response"""
    registry = ModelRegistry.get_instance()
    return {model.id: model.to_dict() for model in registry.get_enabled_models()}


def validate_model_id(model_id: str) -> bool:
    """Check if a model ID exists in registry"""
    registry = ModelRegistry.get_instance()
    return registry.model_exists(model_id)


def get_model_capabilities(model_id: str) -> Optional[Dict[str, Any]]:
    """Get capabilities for a specific model"""
    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id)
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


def get_provider_from_model_id(model_id: str) -> Optional[str]:
    """Get the provider name for a given model_id"""
    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id)
    if model:
        return model.provider.value
    return None


def get_token_limit(model_id: str) -> int:
    """
    Get context window (token limit) for a model.
    Returns model's context_window or default 128000 if model not found.
    """
    from application.core.settings import settings

    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id)
    if model:
        return model.capabilities.context_window
    return settings.DEFAULT_LLM_TOKEN_LIMIT


def get_base_url_for_model(model_id: str) -> Optional[str]:
    """
    Get the custom base_url for a specific model if configured.
    Returns None if no custom base_url is set.
    """
    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id)
    if model:
        return model.base_url
    return None
