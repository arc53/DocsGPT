"""DocsGPT backend version string.

Read from the top-level ``VERSION`` file so release tooling can bump the
version without touching Python code. Cached after first read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

_UNKNOWN = "unknown"
_VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"
_cached: Optional[str] = None


def get_version() -> str:
    """Return the DocsGPT backend version, or ``"unknown"`` if absent.

    A missing ``VERSION`` file is treated as a soft failure — callers
    (notably the startup version check) must never crash because the
    file wasn't shipped with the source checkout.
    """
    global _cached
    if _cached is not None:
        return _cached
    try:
        _cached = _VERSION_PATH.read_text(encoding="utf-8").strip() or _UNKNOWN
    except (FileNotFoundError, OSError):
        _cached = _UNKNOWN
    return _cached


__version__ = get_version()
