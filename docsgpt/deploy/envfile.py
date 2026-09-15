"""Read and update a ``.env`` file in place, keeping the lines the user wrote."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
# Values written without quotes: nothing Compose would interpolate, strip or treat as a comment.
_PLAIN = re.compile(r"^[A-Za-z0-9_./:@+,=-]*$")


def _parse_value(raw: str) -> str:
    """The value of one assignment, with Compose's quoting rules."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", value[1:-1])
    return value.split(" #", 1)[0].rstrip()


def _format_value(value: str) -> str:
    """``value`` quoted so it reads back unchanged."""
    if "\n" in value or "\r" in value:
        raise ValueError("a .env value cannot contain a newline")
    if _PLAIN.match(value):
        return value
    if "'" not in value:
        return f"'{value}'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read(path: Path) -> dict[str, str]:
    """The assignments in ``path`` (empty when it does not exist); a repeated key keeps its last value."""
    path = Path(path)
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            values[match.group(1)] = _parse_value(match.group(2))
    return values


def update(path: Path, values: Mapping[str, Optional[str]]) -> None:
    """Set each key in place (``None`` removes it), append new keys, and leave every other line alone.

    A new file is created readable by its owner only: it holds secrets.
    """
    formatted = {key: None if value is None else _format_value(value) for key, value in values.items()}
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    written: set[str] = set()
    out: list[str] = []
    for line in lines:
        match = _ASSIGNMENT.match(line)
        key = match.group(1) if match else None
        if key not in formatted:
            out.append(line)
            continue
        if key not in written and formatted[key] is not None:
            out.append(f"{key}={formatted[key]}")
        written.add(key)
    out.extend(f"{key}={value}" for key, value in formatted.items() if key not in written and value is not None)

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n" if out else "")
