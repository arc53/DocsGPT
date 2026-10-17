import logging
import uuid

from docsgpt.llm.providers import PROVIDERS_BY_NAME

logger = logging.getLogger(__name__)


class ModelNotAvailableError(ValueError):
    """The requested model is not registered, so it has no endpoint to call."""

    def __init__(self, model_id, reason: str = "") -> None:
        message = f"Model {model_id!r} is not available" if model_id else "No model is available"
        super().__init__(f"{message}{': ' + reason if reason else '.'}")
        self.model_id = model_id


def _is_custom_model_id(model_id) -> bool:
    """True for ids shaped like a user's custom-model record (a UUID)."""
    try:
        uuid.UUID(str(model_id))
    except ValueError:
        return False
    return True


class LLMCreator:
    @classmethod
    def create_llm(
        cls,
        type,
        api_key,
        user_api_key,
        decoded_token,
        model_id=None,
        agent_id=None,
        backup_models=None,
        model_user_id=None,
        *args,
        **kwargs,
    ):
        """Construct an LLM for the given provider ``type``.

        ``model_user_id`` is the BYOM-resolution scope. Defaults to
        ``decoded_token['sub']`` (the caller). Pass it explicitly when
        the model record belongs to a *different* user — most notably
        for shared-agent dispatch, where the agent's stored
        ``default_model_id`` is the owner's BYOM UUID but
        ``decoded_token`` represents the caller.

        A registered model decides its own provider, key and endpoint
        together; the caller's ``type`` and ``api_key`` only stand in for a
        model the registry does not know, and only for a provider whose LLM
        class has a fixed endpoint of its own.

        Raises:
            ModelNotAvailableError: ``model_id`` is not registered and the
                request has no endpoint of its own to go to: the provider is
                ``openai_compatible`` (each of its models carries its own
                endpoint and key), or the id is a custom model's that does not
                resolve. Also raised for ``openai_compatible`` with no model.
            ValueError: ``type`` is not a dispatchable provider, or a custom
                model cannot be dispatched safely.
        """
        from docsgpt.core.model_registry import ModelRegistry
        from docsgpt.security.safe_url import (
            UnsafeUserUrlError,
            pinned_httpx_client,
            validate_user_base_url,
        )

        plugin = PROVIDERS_BY_NAME.get(type.lower())
        if plugin is None or plugin.llm_class is None:
            raise ValueError(f"No LLM class found for type {type}")

        # Prefer per-model endpoint config from the registry. This is what
        # makes openai_compatible AND end-user BYOM work without changing
        # every call site: if the registered AvailableModel carries its
        # own api_key / base_url, they win over whatever the caller
        # resolved via the provider plugin.
        #
        # End-user BYOM lookups need the user_id from decoded_token to
        # find the user's per-user models layer (built-in models resolve
        # without it, so this stays back-compat).
        base_url = None
        upstream_model_id = model_id
        capabilities = None
        model = None
        if model_id:
            user_id = model_user_id
            if user_id is None:
                user_id = (
                    (decoded_token or {}).get("sub") if decoded_token else None
                )
            model = ModelRegistry.get_instance().get_model(model_id, user_id=user_id)
            if model is None:
                # Fail closed. Without a registered model there is no
                # endpoint to pair the key with: the OpenAI client would
                # fall back to OPENAI_BASE_URL or api.openai.com and
                # authenticate with whatever key the caller resolved.
                if plugin.name == "openai_compatible":
                    raise ModelNotAvailableError(
                        model_id,
                        "it is not in the model registry, so it has no endpoint or key of its own.",
                    )
                if _is_custom_model_id(model_id):
                    raise ModelNotAvailableError(
                        model_id,
                        "no custom model with this id is available to this user.",
                    )
            else:
                model_provider = getattr(model, "provider", None)
                model_plugin = PROVIDERS_BY_NAME.get(str(getattr(model_provider, "value", model_provider)))
                if (
                    model_plugin is not None
                    and model_plugin is not plugin
                    and model_plugin.llm_class is not None
                ):
                    # The caller resolved another provider (a stale stored
                    # llm_name, a display label, LLM_PROVIDER). The model's
                    # own provider decides, and the caller's key, resolved
                    # for the other provider, is not sent.
                    logger.info(
                        "Model %s belongs to provider %s, not %s; dispatching it through %s.",
                        model_id,
                        model_plugin.name,
                        plugin.name,
                        model_plugin.name,
                    )
                    plugin = model_plugin
                    api_key = model_plugin.get_api_key(_settings()) or None
                # Forward registry caps so the LLM enforces them at
                # dispatch (built-in classes hard-code True otherwise).
                capabilities = getattr(model, "capabilities", None)
                # SECURITY: refuse user-source dispatch without its own
                # api_key (would leak settings.API_KEY to base_url).
                if (
                    getattr(model, "source", "builtin") == "user"
                    and not model.api_key
                ):
                    raise ValueError(
                        f"Custom model {model_id!r} has no usable API key "
                        "(decryption may have failed). Re-save the model "
                        "in settings to dispatch it."
                    )
                if model.api_key:
                    api_key = model.api_key
                elif plugin.name == "openai_compatible":
                    # Its key travels with its endpoint; a keyless one
                    # (a local server) gets none rather than the caller's.
                    api_key = None
                if model.base_url:
                    base_url = model.base_url
                # For BYOM the registry id is a UUID; the upstream API
                # call needs the user's typed model name instead.
                if model.upstream_model_id:
                    upstream_model_id = model.upstream_model_id

                # SECURITY: re-validate at dispatch (defense in depth
                # for pre-guard rows / YAML-supplied entries). The
                # pinned httpx.Client below is what actually closes the
                # DNS-rebinding TOCTOU window.
                if base_url and getattr(model, "source", "builtin") == "user":
                    try:
                        validate_user_base_url(base_url)
                    except UnsafeUserUrlError as e:
                        raise ValueError(
                            f"Refusing to dispatch model {model_id!r}: {e}"
                        ) from e
                    # Pinned httpx.Client: resolves once, validates, and
                    # binds the SDK's outbound socket to the validated IP
                    # (preserves Host / SNI). Future BYOM providers must
                    # opt in explicitly — only openai_compatible takes
                    # http_client today.
                    if plugin.name == "openai_compatible":
                        try:
                            kwargs["http_client"] = pinned_httpx_client(
                                base_url
                            )
                        except UnsafeUserUrlError as e:
                            raise ValueError(
                                f"Refusing to dispatch model {model_id!r}: {e}"
                            ) from e

        elif plugin.name == "openai_compatible":
            raise ModelNotAvailableError(
                None,
                "openai_compatible needs a model id; its models each carry their own endpoint and key.",
            )

        # Forward model_user_id so backup/fallback resolves under the
        # owner's scope on shared-agent dispatch.
        llm = plugin.llm_class(
            api_key,
            user_api_key,
            decoded_token=decoded_token,
            model_id=upstream_model_id,
            agent_id=agent_id,
            base_url=base_url,
            backup_models=backup_models,
            model_user_id=model_user_id,
            capabilities=capabilities,
            *args,
            **kwargs,
        )
        # llm.model_id is the upstream name (BYOM resolves it above); stamp
        # the canonical id (UUID for BYOM) separately for token_usage.
        llm._canonical_model_id = model_id
        # The provider plugin that built it: ``openai_compatible`` endpoints
        # run through the OpenAI client, so the class alone cannot name them
        # in traces (see ``docsgpt.tracing.llm.llm_provider``).
        llm._provider_plugin = plugin.name
        # Calls to a user's own model are recorded at $0 (see ``docsgpt/usage.py``).
        llm._is_byom = model is not None and getattr(model, "source", "builtin") == "user"
        return llm


def _settings():
    """The process settings (imported lazily, as the rest of this module does)."""
    from docsgpt.core.settings import settings

    return settings
