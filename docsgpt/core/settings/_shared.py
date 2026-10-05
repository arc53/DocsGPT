"""Building blocks shared by the settings groups.

Every group in this package is a :class:`SettingsGroup`: a ``BaseSettings``
subclass that owns one domain's fields. ``docsgpt.core.settings.Settings``
inherits from all of them, so the composed class keeps the flat
``settings.NAME`` attributes the rest of the codebase reads while each
domain's definitions live in their own module.
"""

from __future__ import annotations

import json
import types
import typing
from dataclasses import dataclass
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


@dataclass(frozen=True)
class EnvList:
    """Marks a list setting that reads a JSON list or comma-separated values from the environment.

    Put it in the field's ``Annotated[...]`` next to pydantic-settings' ``NoDecode`` (which stops the
    environment source from insisting on JSON). An empty or whitespace-only value counts as unset, so the
    field keeps its default; on an optional list, ``none`` counts as unset too.

    Attributes:
        none_is_empty: Read ``none`` (any case) as an explicit empty list. Only for fields whose default is
            not empty, where "nothing at all" differs from "unset".
    """

    none_is_empty: bool = False


def parse_env_list(name: str, value: str, marker: EnvList, optional: bool) -> Any:
    """Turn a list setting's raw string into a list, or ``None`` to fall back to the field's default.

    Args:
        name: The setting's name, for error messages.
        value: The raw string from the environment or ``.env``.
        marker: The field's :class:`EnvList` marker.
        optional: Whether the field is ``Optional[list[...]]``.

    Returns:
        The parsed list, or ``None`` when the value means "unset".

    Raises:
        ValueError: If a value that starts with ``[`` is not a valid JSON list.
    """
    text = value.strip()
    if not text or (optional and text.lower() == "none"):
        return None
    if marker.none_is_empty and text.lower() == "none":
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} is not a valid JSON list: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"{name} must be a JSON list")
        return parsed
    return [part.strip() for part in text.split(",") if part.strip()]


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

    @model_validator(mode="before")
    @classmethod
    def _parse_env_lists(cls, data: Any) -> Any:
        """Parse every :class:`EnvList` field given as a string; drop the "unset" ones so the default applies."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for name, field in cls.model_fields.items():
            if not isinstance(data.get(name), str):
                continue
            marker = next((item for item in field.metadata if isinstance(item, EnvList)), None)
            if marker is None:
                continue
            optional = type(None) in typing.get_args(field.annotation)
            parsed = parse_env_list(name, data[name], marker, optional)
            if parsed is None:
                del data[name]
            else:
                data[name] = parsed
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
