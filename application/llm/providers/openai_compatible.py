"""Generic provider for OpenAI-wire-compatible endpoints.

Each ``openai_compatible`` YAML file describes one logical endpoint
(Mistral, Together, Fireworks, Ollama, ...) with its own
``api_key_env`` and ``base_url``. Multiple files can coexist; the
plugin produces one set of models per file, each pre-configured with
the right credentials and URL.

The plugin also handles the **legacy** ``OPENAI_BASE_URL`` + ``LLM_NAME``
local-endpoint pattern that previously lived in ``OpenAIProvider``. That
path generates models dynamically from ``LLM_NAME``, using
``OPENAI_BASE_URL`` and ``OPENAI_API_KEY`` as the endpoint config.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from application.core.model_settings import (
    AvailableModel,
    ModelCapabilities,
    ModelProvider,
)
from application.llm.openai import OpenAILLM
from application.llm.providers.base import Provider

logger = logging.getLogger(__name__)


def _parse_model_names(llm_name: Optional[str]) -> List[str]:
    if not llm_name:
        return []
    return [name.strip() for name in llm_name.split(",") if name.strip()]


class OpenAICompatibleProvider(Provider):
    name = "openai_compatible"
    llm_class = OpenAILLM

    def get_api_key(self, settings) -> Optional[str]:
        # Per-model: each catalog supplies its own ``api_key_env``. There
        # is no single plugin-wide key. LLMCreator reads the per-model
        # ``api_key`` set during catalog materialization.
        return None

    def is_enabled(self, settings) -> bool:
        # Concrete enablement happens per catalog (in ``get_models``).
        # Returning True lets the registry call ``get_models`` so we can
        # decide per-file whether to contribute models.
        return True

    def get_models(self, settings, catalogs) -> List[AvailableModel]:
        out: List[AvailableModel] = []

        for catalog in catalogs:
            out.extend(self._materialize_yaml_catalog(catalog))

        if settings.OPENAI_BASE_URL and settings.LLM_NAME:
            out.extend(self._materialize_legacy_local_endpoint(settings))

        return out

    def _materialize_yaml_catalog(self, catalog) -> List[AvailableModel]:
        """Resolve one openai_compatible YAML into ready-to-dispatch models.

        Skipped (with a warning) if ``api_key_env`` resolves to nothing —
        no point publishing models the user can't actually call.
        """
        if not catalog.base_url:
            raise ValueError(
                f"{catalog.source_path}: openai_compatible YAML must set "
                "'base_url'."
            )
        if not catalog.api_key_env:
            raise ValueError(
                f"{catalog.source_path}: openai_compatible YAML must set "
                "'api_key_env'."
            )

        api_key = os.environ.get(catalog.api_key_env)
        if not api_key:
            logger.info(
                "openai_compatible catalog %s skipped: env var %s is not set",
                catalog.source_path,
                catalog.api_key_env,
            )
            return []

        out: List[AvailableModel] = []
        for m in catalog.models:
            out.append(self._with_endpoint(m, catalog.base_url, api_key))
        return out

    def _materialize_legacy_local_endpoint(self, settings) -> List[AvailableModel]:
        """Generate AvailableModels from ``LLM_NAME`` for the legacy
        ``OPENAI_BASE_URL`` deployment pattern (Ollama, LM Studio, ...).

        Preserves the historical ``provider="openai"`` display behavior
        by setting ``display_provider="openai"``.
        """
        from application.core.model_yaml import resolve_attachment_alias

        attachments = resolve_attachment_alias("image")
        api_key = settings.OPENAI_API_KEY or settings.API_KEY
        out: List[AvailableModel] = []
        for model_name in _parse_model_names(settings.LLM_NAME):
            out.append(
                AvailableModel(
                    id=model_name,
                    provider=ModelProvider.OPENAI_COMPATIBLE,
                    display_name=model_name,
                    description=f"Custom OpenAI-compatible model at {settings.OPENAI_BASE_URL}",
                    base_url=settings.OPENAI_BASE_URL,
                    capabilities=ModelCapabilities(
                        supports_tools=True,
                        supported_attachment_types=attachments,
                    ),
                    api_key=api_key,
                    display_provider="openai",
                )
            )
        return out

    @staticmethod
    def _with_endpoint(
        model: AvailableModel, base_url: str, api_key: str
    ) -> AvailableModel:
        """Return a copy of ``model`` carrying the catalog's endpoint config.

        The catalog-level ``base_url`` is the default; an explicit
        per-model ``base_url`` in the YAML wins.
        """
        return AvailableModel(
            id=model.id,
            provider=model.provider,
            display_name=model.display_name,
            description=model.description,
            capabilities=model.capabilities,
            enabled=model.enabled,
            base_url=model.base_url or base_url,
            display_provider=model.display_provider,
            api_key=api_key,
        )
