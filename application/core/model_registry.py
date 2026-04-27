"""Layered model registry.

Loads model catalogs from YAML files (built-in + operator-supplied),
groups them by provider name, then for each registered provider plugin
calls ``get_models`` to produce the final per-provider model list.

The ``user_id`` parameter on lookup methods is reserved for the future
end-user BYOM (per-user model records in Postgres). It is currently
ignored — defaulted to ``None`` everywhere — so call sites can be
threaded through without a wide refactor when BYOM lands.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from application.core.model_settings import AvailableModel
from application.core.model_yaml import (
    BUILTIN_MODELS_DIR,
    ProviderCatalog,
    load_model_yamls,
)

logger = logging.getLogger(__name__)


class ModelRegistry:
    """Singleton registry of available models."""

    _instance: Optional["ModelRegistry"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not ModelRegistry._initialized:
            self.models: Dict[str, AvailableModel] = {}
            self.default_model_id: Optional[str] = None
            self._load_models()
            ModelRegistry._initialized = True

    @classmethod
    def get_instance(cls) -> "ModelRegistry":
        return cls()

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton. Intended for test fixtures."""
        cls._instance = None
        cls._initialized = False

    def _load_models(self) -> None:
        from pathlib import Path

        from application.core.settings import settings
        from application.llm.providers import ALL_PROVIDERS

        directories = [BUILTIN_MODELS_DIR]
        operator_dir = getattr(settings, "MODELS_CONFIG_DIR", None)
        if operator_dir:
            op_path = Path(operator_dir)
            if not op_path.exists():
                logger.warning(
                    "MODELS_CONFIG_DIR=%s does not exist; no operator "
                    "model YAMLs will be loaded.",
                    operator_dir,
                )
            elif not op_path.is_dir():
                logger.warning(
                    "MODELS_CONFIG_DIR=%s is not a directory; no operator "
                    "model YAMLs will be loaded.",
                    operator_dir,
                )
            else:
                directories.append(op_path)

        catalogs = load_model_yamls(directories)

        # Validate every catalog targets a known plugin before doing any
        # registry work, so an unknown provider name in YAML aborts boot
        # with a clear error.
        plugin_names = {p.name for p in ALL_PROVIDERS}
        for c in catalogs:
            if c.provider not in plugin_names:
                raise ValueError(
                    f"{c.source_path}: YAML declares unknown provider "
                    f"{c.provider!r}; no Provider plugin is registered "
                    f"under that name. Known: {sorted(plugin_names)}"
                )

        catalogs_by_provider: Dict[str, List[ProviderCatalog]] = defaultdict(list)
        for c in catalogs:
            catalogs_by_provider[c.provider].append(c)

        self.models.clear()
        for provider in ALL_PROVIDERS:
            if not provider.is_enabled(settings):
                continue
            for model in provider.get_models(
                settings, catalogs_by_provider.get(provider.name, [])
            ):
                self.models[model.id] = model

        self.default_model_id = self._resolve_default(settings)

        logger.info(
            "ModelRegistry loaded %d models, default: %s",
            len(self.models),
            self.default_model_id,
        )

    def _resolve_default(self, settings) -> Optional[str]:
        if settings.LLM_NAME:
            for name in self._parse_model_names(settings.LLM_NAME):
                if name in self.models:
                    return name
            if settings.LLM_NAME in self.models:
                return settings.LLM_NAME

        if settings.LLM_PROVIDER and settings.API_KEY:
            for model_id, model in self.models.items():
                if model.provider.value == settings.LLM_PROVIDER:
                    return model_id

        if self.models:
            return next(iter(self.models.keys()))
        return None

    @staticmethod
    def _parse_model_names(llm_name: str) -> List[str]:
        if not llm_name:
            return []
        return [name.strip() for name in llm_name.split(",") if name.strip()]

    # ------------------------------------------------------------------
    # Lookup API. ``user_id`` is reserved for the future BYOM and
    # is ignored today — but threading it through every call site now
    # means BYOM doesn't require a wide refactor when we build it.
    # ------------------------------------------------------------------

    def get_model(
        self, model_id: str, user_id: Optional[str] = None
    ) -> Optional[AvailableModel]:
        return self.models.get(model_id)

    def get_all_models(
        self, user_id: Optional[str] = None
    ) -> List[AvailableModel]:
        return list(self.models.values())

    def get_enabled_models(
        self, user_id: Optional[str] = None
    ) -> List[AvailableModel]:
        return [m for m in self.models.values() if m.enabled]

    def model_exists(
        self, model_id: str, user_id: Optional[str] = None
    ) -> bool:
        return model_id in self.models
