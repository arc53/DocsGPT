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
        *args,
        **kwargs,
    ):
        from application.core.model_registry import ModelRegistry

        plugin = PROVIDERS_BY_NAME.get(type.lower())
        if plugin is None or plugin.llm_class is None:
            raise ValueError(f"No LLM class found for type {type}")

        # Prefer per-model endpoint config from the registry. This is what
        # makes openai_compatible (and the future end-user BYOM phase)
        # work without changing every call site: if the registered
        # AvailableModel carries its own api_key / base_url, they win
        # over whatever the caller resolved via the provider plugin.
        base_url = None
        if model_id:
            model = ModelRegistry.get_instance().get_model(model_id)
            if model is not None:
                if model.api_key:
                    api_key = model.api_key
                if model.base_url:
                    base_url = model.base_url

        return plugin.llm_class(
            api_key,
            user_api_key,
            decoded_token=decoded_token,
            model_id=model_id,
            agent_id=agent_id,
            base_url=base_url,
            backup_models=backup_models,
            *args,
            **kwargs,
        )
