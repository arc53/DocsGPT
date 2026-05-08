"""Layered model registry.

Loads model catalogs from YAML files (built-in + operator-supplied),
groups them by provider name, then for each registered provider plugin
calls ``get_models`` to produce the final per-provider model list.

End-user BYOM (per-user model records in Postgres) is layered on top:
when a lookup arrives with a ``user_id``, the registry consults a
per-user cache first (loaded from the ``user_custom_models`` table on
miss) and falls through to the built-in catalog.

Cross-process invalidation: ``ModelRegistry`` is a per-process
singleton, so a CRUD write only evicts the cache in the process that
served it. Other gunicorn workers and Celery workers would otherwise
keep using a deleted/disabled/key-rotated BYOM record indefinitely.
``invalidate_user`` therefore both drops the local layer *and* bumps a
Redis-side version counter; other processes notice the bump on their
next access (after the local TTL window) and reload from Postgres. If
Redis is unreachable the per-process TTL still bounds staleness — pure
TTL semantics, no regression.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from application.core.model_settings import AvailableModel
from application.core.model_yaml import (
    BUILTIN_MODELS_DIR,
    ProviderCatalog,
    load_model_yamls,
)

logger = logging.getLogger(__name__)

_USER_CACHE_TTL_SECONDS = 60.0
_USER_VERSION_KEY_PREFIX = "byom:registry_version:"


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
            # Per-user BYOM cache. Each entry is
            # ``(layer, version_at_load, loaded_at_monotonic)``:
            #   * ``layer`` — {model_id: AvailableModel}
            #   * ``version_at_load`` — Redis-side counter snapshot at
            #     reload time, or ``None`` if Redis was unreachable
            #   * ``loaded_at_monotonic`` — for TTL bookkeeping
            # Populated lazily, evicted by TTL + cross-process
            # invalidation (see ``invalidate_user``).
            self._user_models: Dict[
                str,
                Tuple[Dict[str, AvailableModel], Optional[int], float],
            ] = {}
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

    @classmethod
    def invalidate_user(cls, user_id: str) -> None:
        """Drop the cached per-user model layer for ``user_id``.

        Called by the BYOM REST routes after every create/update/delete.
        Two effects:

        * Local: pop the entry from this process's cache so the next
          lookup re-reads from Postgres immediately.
        * Cross-process: ``INCR`` a Redis-side version counter for this
          user. Other gunicorn/Celery processes notice the counter
          changed on their next TTL-driven recheck (see
          ``_user_models_for``) and reload. If Redis is unreachable we
          log and continue — local invalidation still happened, and
          peers fall back to TTL-only staleness bounds.
        """
        if cls._instance is not None:
            cls._instance._user_models.pop(user_id, None)
        try:
            from application.cache import get_redis_instance

            client = get_redis_instance()
            if client is not None:
                client.incr(_USER_VERSION_KEY_PREFIX + user_id)
        except Exception as e:
            logger.warning(
                "BYOM invalidate: failed to publish version bump for "
                "user %s (Redis unreachable?): %s",
                user_id,
                e,
            )

    @classmethod
    def _read_user_version(cls, user_id: str) -> Optional[int]:
        """Return the Redis-side invalidation counter for ``user_id``.

        ``0`` if the key has never been bumped; ``None`` if Redis is
        unreachable or the read failed (callers fall back to TTL-only
        staleness in that case).
        """
        try:
            from application.cache import get_redis_instance

            client = get_redis_instance()
            if client is None:
                return None
            raw = client.get(_USER_VERSION_KEY_PREFIX + user_id)
            if raw is None:
                return 0
            return int(raw)
        except Exception:
            return None

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

    # Per-user (BYOM) layer

    def _user_models_for(self, user_id: str) -> Dict[str, AvailableModel]:
        """Return the user's BYOM models keyed by registry id (UUID).

        Loaded lazily from Postgres on first access; cached subject to
        a per-process TTL (``_USER_CACHE_TTL_SECONDS``) and a Redis-
        backed version counter for cross-process invalidation. The TTL
        bounds staleness even when Redis is unreachable, while the
        version stamp lets peers refresh without a DB read on the
        common case (no invalidation since last load). Decryption
        failures and DB errors yield an empty layer (logged) — the
        user simply doesn't see their custom models on this request,
        never a 500.
        """
        cached = self._user_models.get(user_id)
        now = time.monotonic()

        if cached is not None:
            layer, cached_version, loaded_at = cached
            if (now - loaded_at) < _USER_CACHE_TTL_SECONDS:
                return layer
            # TTL elapsed: peek at the cross-process counter. If it
            # matches what we saw at load time, no invalidation has
            # happened — extend the TTL without touching Postgres. If
            # Redis is unreachable (``current_version is None``) we
            # fall through to a real reload, which keeps staleness
            # bounded to the TTL.
            current_version = self._read_user_version(user_id)
            if (
                current_version is not None
                and cached_version is not None
                and current_version == cached_version
            ):
                self._user_models[user_id] = (layer, cached_version, now)
                return layer

        # Capture the counter *before* the DB read so a CRUD that lands
        # mid-reload doesn't get masked: the next access will see a
        # newer version and reload again.
        version_before_read = self._read_user_version(user_id)

        layer: Dict[str, AvailableModel] = {}
        try:
            from application.core.model_settings import (
                ModelCapabilities,
                ModelProvider,
            )
            from application.storage.db.repositories.user_custom_models import (
                UserCustomModelsRepository,
            )
            from application.storage.db.session import db_readonly

            with db_readonly() as conn:
                repo = UserCustomModelsRepository(conn)
                rows = repo.list_for_user(user_id)
                for row in rows:
                    api_key = repo._decrypt_api_key(
                        row.get("api_key_encrypted", ""), user_id
                    )
                    if not api_key:
                        # SECURITY: do NOT register an unroutable BYOM
                        # record. If we did, LLMCreator would fall back
                        # to the caller-passed api_key (settings.API_KEY
                        # for openai_compatible) and POST it to the
                        # user-supplied base_url — leaking the instance
                        # credential to the user's chosen endpoint.
                        # Most likely cause is ENCRYPTION_SECRET_KEY
                        # having rotated; user must re-save the model.
                        logger.warning(
                            "user_custom_models: skipping model %s for "
                            "user %s — api_key could not be decrypted "
                            "(rotated ENCRYPTION_SECRET_KEY?). Re-save "
                            "the model to recover.",
                            row.get("id"),
                            user_id,
                        )
                        continue
                    caps_raw = row.get("capabilities") or {}
                    # Stored attachments may be aliases (``image``) or
                    # raw MIME types. Built-in YAML models expand at
                    # load time; mirror that here so downstream MIME-
                    # type comparisons (handlers/base.prepare_messages)
                    # match concrete types like ``image/png`` rather
                    # than the bare alias.
                    from application.core.model_yaml import (
                        expand_attachments_lenient,
                    )

                    raw_attachments = caps_raw.get("attachments", []) or []
                    expanded_attachments = expand_attachments_lenient(
                        raw_attachments,
                        f"user_custom_models[user={user_id}, model={row.get('id')}]",
                    )
                    caps = ModelCapabilities(
                        supports_tools=bool(caps_raw.get("supports_tools", False)),
                        supports_structured_output=bool(
                            caps_raw.get("supports_structured_output", False)
                        ),
                        supports_streaming=bool(
                            caps_raw.get("supports_streaming", True)
                        ),
                        supported_attachment_types=expanded_attachments,
                        context_window=int(
                            caps_raw.get("context_window") or 128000
                        ),
                    )
                    model_id = str(row["id"])
                    layer[model_id] = AvailableModel(
                        id=model_id,
                        provider=ModelProvider.OPENAI_COMPATIBLE,
                        display_name=row["display_name"],
                        description=row.get("description") or "",
                        capabilities=caps,
                        enabled=bool(row.get("enabled", True)),
                        base_url=row["base_url"],
                        upstream_model_id=row["upstream_model_id"],
                        source="user",
                        api_key=api_key,
                    )
        except Exception as e:
            logger.warning(
                "user_custom_models: failed to load layer for user %s: %s",
                user_id,
                e,
            )
            layer = {}

        self._user_models[user_id] = (layer, version_before_read, now)
        return layer

    # Lookup API. ``user_id`` enables the BYOM per-user layer; without
    # it, callers see only the built-in + operator catalog.

    def get_model(
        self, model_id: str, user_id: Optional[str] = None
    ) -> Optional[AvailableModel]:
        if user_id:
            user_layer = self._user_models_for(user_id)
            if model_id in user_layer:
                return user_layer[model_id]
        return self.models.get(model_id)

    def get_all_models(
        self, user_id: Optional[str] = None
    ) -> List[AvailableModel]:
        out = list(self.models.values())
        if user_id:
            out.extend(self._user_models_for(user_id).values())
        return out

    def get_enabled_models(
        self, user_id: Optional[str] = None
    ) -> List[AvailableModel]:
        out = [m for m in self.models.values() if m.enabled]
        if user_id:
            out.extend(
                m for m in self._user_models_for(user_id).values() if m.enabled
            )
        return out

    def model_exists(
        self, model_id: str, user_id: Optional[str] = None
    ) -> bool:
        if user_id and model_id in self._user_models_for(user_id):
            return True
        return model_id in self.models
