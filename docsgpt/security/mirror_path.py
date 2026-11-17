"""Validation for source paths mirrored from another filesystem."""

import re

_FORBIDDEN = re.compile(r'[<>:"\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{suffix}" for prefix in ("COM", "LPT") for suffix in "123456789¹²³"
}


class InvalidMirrorPath(ValueError):
    """A path cannot be mirrored safely without renaming it."""


def validate_mirror_path(name: str) -> str:
    """Return a portable relative path exactly as supplied, or reject it."""
    parts = name.split("/")
    if len(parts) > 64 or len(name.encode("utf-8")) > 4096:
        raise InvalidMirrorPath("Mirror path exceeds the safety limit")
    for part in parts:
        if (
            not part
            or part.endswith((" ", "."))
            or _FORBIDDEN.search(part)
            or part.partition(".")[0].upper() in _RESERVED
            or len(part.encode("utf-8")) > 255
        ):
            raise InvalidMirrorPath("Mirror path contains an unsupported component")
    return name
