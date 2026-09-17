"""Building blocks shared by the settings groups.

Every group in this package is a :class:`SettingsGroup`: a ``BaseSettings``
subclass that owns one domain's fields. ``docsgpt.core.settings.Settings``
inherits from all of them, so the composed class keeps the flat
``settings.NAME`` attributes the rest of the codebase reads while each
domain's definitions live in their own module.
"""

from __future__ import annotations

import types
import typing
from typing import Any, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_optional_str(annotation: Any) -> bool:
    """``Optional[str]`` or ``Optional[Literal[...]]`` whose choices are all strings."""
    if typing.get_origin(annotation) not in (typing.Union, types.UnionType):
        return False
    members = set(typing.get_args(annotation))
    if type(None) not in members or len(members) != 2:
        return False
    (member,) = members - {type(None)}
    if member is str:
        return True
    return typing.get_origin(member) is typing.Literal and all(
        isinstance(choice, str) for choice in typing.get_args(member)
    )


class SettingsGroup(BaseSettings):
    """Base for one domain's settings; groups are composed into ``Settings``.

    Every ``Optional[str]`` field (and optional string ``Literal``) treats the spellings an unset value has in a
    ``.env`` file (``KEY=``, ``KEY=None``, whitespace) as ``None``, so a check
    like ``if settings.OIDC_ISSUER`` or a fallback like ``settings.X or default``
    sees "unset" rather than a truthy placeholder string. Real values are
    stripped. Fields typed ``str`` keep whatever they are given.
    """

    model_config = SettingsConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _unset_optional_strings(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for name, field in cls.model_fields.items():
            if name in data and _is_optional_str(field.annotation):
                data[name] = normalize_secret(data[name])
        return data


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
