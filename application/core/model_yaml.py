"""YAML loader for model catalog files under ``application/core/models/``.

Each ``*.yaml`` file declares one provider's static model catalog. Files
are validated with Pydantic at load time; any parse, schema, or alias
error aborts startup with the offending file path in the message.

For most providers, one YAML maps to one catalog. The
``openai_compatible`` provider is special: each YAML file represents a
distinct logical endpoint (Mistral, Together, Ollama, ...) with its own
``api_key_env`` and ``base_url``. The loader returns a flat list so the
registry can distinguish multiple files with the same ``provider:`` value.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.core.model_settings import (
    AvailableModel,
    ModelCapabilities,
    ModelProvider,
)

logger = logging.getLogger(__name__)

BUILTIN_MODELS_DIR = Path(__file__).parent / "models"
DEFAULTS_FILENAME = "_defaults.yaml"


class _DefaultsFile(BaseModel):
    """Schema for ``_defaults.yaml``. Currently just attachment aliases."""

    model_config = ConfigDict(extra="forbid")

    attachment_aliases: Dict[str, List[str]] = Field(default_factory=dict)


class _CapabilityFields(BaseModel):
    """Capability fields shared between provider ``defaults:`` and per-model overrides.

    All fields are optional so a per-model override can selectively replace
    a single field from the provider-level defaults.
    """

    model_config = ConfigDict(extra="forbid")

    supports_tools: Optional[bool] = None
    supports_structured_output: Optional[bool] = None
    supports_streaming: Optional[bool] = None
    attachments: Optional[List[str]] = None
    context_window: Optional[int] = None
    input_cost_per_token: Optional[float] = None
    output_cost_per_token: Optional[float] = None


class _ModelEntry(_CapabilityFields):
    """Schema for one model row inside a YAML's ``models:`` list."""

    id: str
    display_name: Optional[str] = None
    description: str = ""
    enabled: bool = True
    base_url: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("model id must be a non-empty string")
        return v


class _ProviderFile(BaseModel):
    """Schema for one ``<provider>.yaml`` catalog file."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    defaults: _CapabilityFields = Field(default_factory=_CapabilityFields)
    models: List[_ModelEntry] = Field(default_factory=list)
    # openai_compatible metadata. Optional for other providers.
    display_provider: Optional[str] = None
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None


class ProviderCatalog(BaseModel):
    """One YAML file's parsed contents, ready for the registry.

    For most providers, multiple catalogs with the same ``provider`` get
    merged later by the registry. The ``openai_compatible`` provider is
    the exception: each catalog is treated as a distinct endpoint, with
    its own ``api_key_env`` and ``base_url``.
    """

    provider: str
    models: List[AvailableModel]
    source_path: Optional[Path] = None
    display_provider: Optional[str] = None
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ModelYAMLError(ValueError):
    """Raised when a model YAML fails parsing, schema, or alias validation."""


def _expand_attachments(
    attachments: Sequence[str], aliases: Dict[str, List[str]], source: str
) -> List[str]:
    """Resolve attachment shorthands (``image``, ``pdf``) to MIME types.

    Raw MIME-typed entries (containing ``/``) pass through unchanged.
    Unknown aliases raise ``ModelYAMLError``.
    """
    expanded: List[str] = []
    seen: set = set()
    for entry in attachments:
        if "/" in entry:
            if entry not in seen:
                expanded.append(entry)
                seen.add(entry)
            continue
        if entry not in aliases:
            valid = ", ".join(sorted(aliases.keys())) or "<none defined>"
            raise ModelYAMLError(
                f"{source}: unknown attachment alias '{entry}'. "
                f"Valid aliases: {valid}. "
                "(Or use a raw MIME type like 'image/png'.)"
            )
        for mime in aliases[entry]:
            if mime not in seen:
                expanded.append(mime)
                seen.add(mime)
    return expanded


def _load_defaults(directory: Path) -> Dict[str, List[str]]:
    """Load ``_defaults.yaml`` from ``directory`` if it exists."""
    path = directory / DEFAULTS_FILENAME
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ModelYAMLError(f"{path}: invalid YAML: {e}") from e
    try:
        parsed = _DefaultsFile.model_validate(raw)
    except Exception as e:
        raise ModelYAMLError(f"{path}: schema error: {e}") from e
    return parsed.attachment_aliases


def _resolve_provider_enum(name: str, source: Path) -> ModelProvider:
    try:
        return ModelProvider(name)
    except ValueError as e:
        valid = ", ".join(p.value for p in ModelProvider)
        raise ModelYAMLError(
            f"{source}: unknown provider '{name}'. Valid: {valid}"
        ) from e


def _build_model(
    entry: _ModelEntry,
    defaults: _CapabilityFields,
    provider: ModelProvider,
    aliases: Dict[str, List[str]],
    source: Path,
    display_provider: Optional[str] = None,
) -> AvailableModel:
    """Merge defaults + per-model overrides into a final ``AvailableModel``."""

    def pick(field_name: str, fallback):
        v = getattr(entry, field_name)
        if v is not None:
            return v
        d = getattr(defaults, field_name)
        if d is not None:
            return d
        return fallback

    raw_attachments = entry.attachments
    if raw_attachments is None:
        raw_attachments = defaults.attachments
    if raw_attachments is None:
        raw_attachments = []
    expanded = _expand_attachments(
        raw_attachments, aliases, f"{source} [model={entry.id}]"
    )

    caps = ModelCapabilities(
        supports_tools=pick("supports_tools", False),
        supports_structured_output=pick("supports_structured_output", False),
        supports_streaming=pick("supports_streaming", True),
        supported_attachment_types=expanded,
        context_window=pick("context_window", 128000),
        input_cost_per_token=pick("input_cost_per_token", None),
        output_cost_per_token=pick("output_cost_per_token", None),
    )

    return AvailableModel(
        id=entry.id,
        provider=provider,
        display_name=entry.display_name or entry.id,
        description=entry.description,
        capabilities=caps,
        enabled=entry.enabled,
        base_url=entry.base_url,
        display_provider=display_provider,
    )


def _load_one_yaml(
    path: Path, aliases: Dict[str, List[str]]
) -> ProviderCatalog:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ModelYAMLError(f"{path}: invalid YAML: {e}") from e
    try:
        parsed = _ProviderFile.model_validate(raw)
    except Exception as e:
        raise ModelYAMLError(f"{path}: schema error: {e}") from e

    provider_enum = _resolve_provider_enum(parsed.provider, path)
    models = [
        _build_model(
            entry,
            parsed.defaults,
            provider_enum,
            aliases,
            path,
            display_provider=parsed.display_provider,
        )
        for entry in parsed.models
    ]

    return ProviderCatalog(
        provider=parsed.provider,
        models=models,
        source_path=path,
        display_provider=parsed.display_provider,
        api_key_env=parsed.api_key_env,
        base_url=parsed.base_url,
    )


_BUILTIN_ALIASES_CACHE: Optional[Dict[str, List[str]]] = None


def builtin_attachment_aliases() -> Dict[str, List[str]]:
    """Return the built-in attachment alias map from ``_defaults.yaml``.

    Cached after first read so repeat calls are cheap.
    """
    global _BUILTIN_ALIASES_CACHE
    if _BUILTIN_ALIASES_CACHE is None:
        _BUILTIN_ALIASES_CACHE = _load_defaults(BUILTIN_MODELS_DIR)
    return _BUILTIN_ALIASES_CACHE


def resolve_attachment_alias(alias: str) -> List[str]:
    """Resolve a single attachment alias (e.g. ``"image"``) to its
    canonical MIME-type list. Raises ``ModelYAMLError`` if unknown.
    """
    aliases = builtin_attachment_aliases()
    if alias not in aliases:
        valid = ", ".join(sorted(aliases.keys())) or "<none defined>"
        raise ModelYAMLError(
            f"Unknown attachment alias '{alias}'. Valid: {valid}"
        )
    return list(aliases[alias])


def load_model_yamls(directories: Sequence[Path]) -> List[ProviderCatalog]:
    """Load every ``*.yaml`` file (excluding ``_defaults.yaml``) under each
    directory in order and return a flat list of catalogs.

    Caller is responsible for merging multiple catalogs that target the
    same provider plugin. The flat-list shape lets ``openai_compatible``
    keep each file separate (one logical endpoint per file).

    When the same model ``id`` appears in more than one YAML across the
    directory list, a warning is logged. Order in the returned list
    preserves load order, so the registry's "later wins" merge gives the
    later directory's definition.
    """
    catalogs: List[ProviderCatalog] = []
    seen_ids: Dict[str, Path] = {}

    aliases: Dict[str, List[str]] = {}
    for d in directories:
        if not d or not d.exists():
            continue
        aliases.update(_load_defaults(d))

    for d in directories:
        if not d or not d.exists():
            continue
        for path in sorted(d.glob("*.yaml")):
            if path.name == DEFAULTS_FILENAME:
                continue
            catalog = _load_one_yaml(path, aliases)
            catalogs.append(catalog)
            for m in catalog.models:
                prior = seen_ids.get(m.id)
                if prior is not None and prior != path:
                    logger.warning(
                        "Model id %r redefined: %s overrides %s (later wins)",
                        m.id,
                        path,
                        prior,
                    )
                seen_ids[m.id] = path

    return catalogs
