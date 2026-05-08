from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, List, Optional, Type

if TYPE_CHECKING:
    from application.core.model_settings import AvailableModel
    from application.core.model_yaml import ProviderCatalog
    from application.core.settings import Settings
    from application.llm.base import BaseLLM


class Provider(ABC):
    """Owns the *behavior* of an LLM provider.

    Concrete providers declare their name, the LLM class to instantiate,
    and how to resolve credentials from settings. Static model catalogs
    live in YAML under ``application/core/models/`` and are joined to the
    provider by name at registry load time.

    Most plugins receive zero or one catalog at registry-build time. The
    ``openai_compatible`` plugin is the exception: it receives one catalog
    per matching YAML file, each with its own ``api_key_env`` and
    ``base_url``. Plugins that need per-catalog metadata override
    ``get_models``; the default implementation merges catalogs and routes
    through ``filter_yaml_models`` + ``extra_models``.
    """

    name: ClassVar[str]
    # ``None`` means the provider appears in the catalog but isn't
    # dispatchable through LLMCreator (e.g. Hugging Face today, where the
    # original LLMCreator dict had no entry).
    llm_class: ClassVar[Optional[Type["BaseLLM"]]] = None

    @abstractmethod
    def get_api_key(self, settings: "Settings") -> Optional[str]:
        """Return the API key for this provider, or None if unavailable."""

    def is_enabled(self, settings: "Settings") -> bool:
        """Whether this provider should contribute models to the registry."""
        return bool(self.get_api_key(settings))

    def filter_yaml_models(
        self, settings: "Settings", models: List["AvailableModel"]
    ) -> List["AvailableModel"]:
        """Hook to filter YAML-loaded models. Default: return all."""
        return models

    def extra_models(self, settings: "Settings") -> List["AvailableModel"]:
        """Hook to add dynamic models not declared in YAML. Default: none."""
        return []

    def get_models(
        self,
        settings: "Settings",
        catalogs: List["ProviderCatalog"],
    ) -> List["AvailableModel"]:
        """Final list of models this plugin contributes.

        Default: merge the models across all matched catalogs (later
        catalog wins on duplicate id), filter via ``filter_yaml_models``,
        then append ``extra_models``. Override when per-catalog metadata
        matters (see ``OpenAICompatibleProvider``).
        """
        merged: List["AvailableModel"] = []
        seen: dict = {}
        for c in catalogs:
            for m in c.models:
                if m.id in seen:
                    merged[seen[m.id]] = m
                else:
                    seen[m.id] = len(merged)
                    merged.append(m)
        return self.filter_yaml_models(settings, merged) + self.extra_models(settings)
