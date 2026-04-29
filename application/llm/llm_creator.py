import logging

from application.llm.providers import PROVIDERS_BY_NAME

logger = logging.getLogger(__name__)


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
        """
        from application.core.model_registry import ModelRegistry
        from application.security.safe_url import (
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
        if model_id:
            user_id = model_user_id
            if user_id is None:
                user_id = (
                    (decoded_token or {}).get("sub") if decoded_token else None
                )
            model = ModelRegistry.get_instance().get_model(model_id, user_id=user_id)
            if model is not None:
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

        # Forward model_user_id so backup/fallback resolves under the
        # owner's scope on shared-agent dispatch.
        return plugin.llm_class(
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
