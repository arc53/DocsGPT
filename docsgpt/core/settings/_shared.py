"""Building blocks shared by the settings groups.

Every group in this package is a :class:`SettingsGroup`: a ``BaseSettings``
subclass that owns one domain's fields. ``docsgpt.core.settings.Settings``
inherits from all of them, so the composed class keeps the flat
``settings.NAME`` attributes the rest of the codebase reads while each
domain's definitions live in their own module.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsGroup(BaseSettings):
    """Base for one domain's settings; groups are composed into ``Settings``."""

    model_config = SettingsConfigDict(extra="ignore")


def normalize_choice(value: Any) -> Any:
    """Case-fold a closed-choice setting so ``PGVector`` and ``pgvector`` are the same choice."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


def normalize_secret(value: Optional[str]) -> Optional[str]:
    """Map the ways an unset secret reaches us from ``.env`` to ``None``.

    ``.env`` files carry ``KEY=None`` and ``KEY=`` for "not set", and pydantic
    would otherwise keep those as the strings ``"None"`` and ``""``. Whitespace
    around a real value is stripped.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped == "" or stripped.lower() == "none":
        return None
    return stripped
