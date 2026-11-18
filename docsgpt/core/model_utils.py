import logging
from typing import Any, Dict, Optional, Tuple

from docsgpt.core.model_registry import ModelRegistry

logger = logging.getLogger(__name__)


def get_api_key_for_provider(provider: Optional[str]) -> Optional[str]:
    """Return the deployment's own API key for ``provider``.

    Delegates to the provider plugin's ``get_api_key``: the provider's key
    setting, or the generic ``API_KEY`` when ``provider`` is ``LLM_PROVIDER``.

    There is no fallback to ``API_KEY`` beyond that. ``API_KEY`` belongs to
    ``LLM_PROVIDER``; handing it to another provider, an unknown name, or
    ``openai_compatible`` (whose models each carry their own key and
    endpoint) would send it to an endpoint it does not belong to.

    Args:
        provider: A provider plugin name, e.g. ``openai``.

    Returns:
        The key, or ``None`` when the provider has none configured.
    """
    from docsgpt.core.settings import settings
    from docsgpt.llm.providers import PROVIDERS_BY_NAME

    plugin = PROVIDERS_BY_NAME.get((provider or "").lower())
    if plugin is None:
        return None
    return plugin.get_api_key(settings) or None


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
    from docsgpt.llm.providers import PROVIDERS_BY_NAME

    # Return the *canonical* lowercase name, so every later lookup (key,
    # handler, LLM class) agrees on which provider this is.
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
            "api_flavor": model.capabilities.api_flavor,
        }
    return None


def get_default_model_id() -> str:
    """Get the system default model ID"""
    registry = ModelRegistry.get_instance()
    return registry.default_model_id


def model_is_usable(model_id: Optional[str], user_id: Optional[str] = None) -> bool:
    """Whether ``model_id`` names an enabled model ``user_id`` can run.

    Stricter than :func:`validate_model_id`, which also accepts a disabled
    model. Without ``user_id`` only built-in catalog models count, so a
    custom (BYOM) model, which resolves for its owner alone, is never usable.

    Args:
        model_id: The model id to check.
        user_id: The user whose custom models count too.

    Returns:
        True when the registry resolves it for that user and it is enabled.
    """
    if not isinstance(model_id, str) or not model_id.strip():
        return False
    model = ModelRegistry.get_instance().get_model(model_id, user_id=user_id)
    return model is not None and bool(getattr(model, "enabled", True))


def _stored_task_models(user_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """The user's and the instance's stored task model; ``(None, None)`` when the database can't answer.

    A job never fails on this read: a database error leaves the choice to
    ``TASK_MODEL_ID`` and the default model.
    """
    try:
        from docsgpt.storage.db import model_defaults
        from docsgpt.storage.db.session import db_readonly

        with db_readonly() as conn:
            return model_defaults.stored_task_models(conn, user_id)
    except Exception:
        logger.warning("Could not read the stored task model; using TASK_MODEL_ID or the default", exc_info=True)
        return None, None


#: ``TASK_MODEL_ID`` values already warned about, so a misconfigured one logs once, not on every job.
_warned_task_model_ids: set[str] = set()


def resolve_task_model_id(
    user_id: Optional[str],
    user_choice: Optional[str],
    instance_choice: Optional[str],
) -> Optional[str]:
    """The task model from stored choices: the user's, the instance's, ``TASK_MODEL_ID``, the default model.

    Each choice must name a model that can run (:func:`model_is_usable`), or
    it is skipped without an error: a model removed from the catalog, a
    disabled or deleted custom model. The default model is held to the same
    rule. The user's may be one of their own custom models; the instance's
    and ``TASK_MODEL_ID`` are built-in only. A ``TASK_MODEL_ID`` that can't
    run is logged once per value.

    Args:
        user_id: The user the job runs as; ``None`` skips ``user_choice``.
        user_choice: The user's stored ``task_model_id``.
        instance_choice: The admin's stored instance task model.

    Returns:
        A model id, or ``None`` when no step names a model that can run.
    """
    from docsgpt.core.settings import settings

    if user_id and model_is_usable(user_choice, user_id):
        return user_choice.strip()
    if model_is_usable(instance_choice):
        return instance_choice.strip()
    configured = (settings.TASK_MODEL_ID or "").strip()
    if configured:
        if model_is_usable(configured):
            return configured
        if configured not in _warned_task_model_ids:
            _warned_task_model_ids.add(configured)
            logger.warning("TASK_MODEL_ID %r is not an enabled built-in model; using the default model", configured)
    default = get_default_model_id()
    return default if model_is_usable(default) else None


def get_task_model_id(user_id: Optional[str]) -> Optional[str]:
    """The model DocsGPT's own jobs run on for ``user_id``: the drafter, graph extraction, the monitor judge.

    In order: the user's choice in Settings > General (their own custom
    models included, since they pay with their own key), the instance's in
    Admin > Defaults, ``TASK_MODEL_ID``, then the default model. A stored
    admin choice wins over the environment, as stored instance settings do
    elsewhere (the guardrails floor). Chats keep the agent's model.

    Args:
        user_id: The user the job runs as (a graph build's source owner, a
            monitor's owner); ``None`` for the instance's task model.

    Returns:
        A model id, or ``None`` when no step names a model that can run.
    """
    user_choice, instance_choice = _stored_task_models(user_id)
    return resolve_task_model_id(user_id, user_choice, instance_choice)


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
    from docsgpt.core.settings import settings

    registry = ModelRegistry.get_instance()
    model = registry.get_model(model_id, user_id=user_id)
    if model:
        return model.capabilities.context_window
    return settings.DEFAULT_LLM_TOKEN_LIMIT


def get_context_budget(
    model_id: str,
    user_id: Optional[str] = None,
    context_window_limit: Optional[int] = None,
) -> int:
    """Tokens a request may fill: the model's window, lowered to the agent's context limit.

    Budgets (compression threshold, history, documents, attachments) read
    this. Checks of what the provider will accept keep ``get_token_limit``:
    the limit is a cost target, so it never refuses a request the model can
    take.

    Args:
        model_id: The model the request runs on.
        user_id: BYOM-resolution scope, as for ``get_token_limit``.
        context_window_limit: The agent's ``config.context_window_limit``;
            None, or one at or above the window, leaves the window as it is.

    Returns:
        The budget in tokens.
    """
    return cap_context_window(get_token_limit(model_id, user_id=user_id), context_window_limit)


def cap_context_window(window: int, context_window_limit: Optional[int]) -> int:
    """``window`` lowered to ``context_window_limit``; None or a higher limit leaves it.

    Args:
        window: The model's context window.
        context_window_limit: The agent's ``config.context_window_limit``.

    Returns:
        The smaller of the two.
    """
    if context_window_limit and context_window_limit < window:
        return int(context_window_limit)
    return window


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
