"""The request ``passthrough`` values as they are stored with a turn.

Prompt rendering reads the raw request (``PassthroughNamespace``). What is kept
on the conversation and the turn's Logs row is the same scalar-only view, with
the number of keys and the length of keys and strings bounded so a caller
cannot grow every log row without limit.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

MAX_KEYS = 32
MAX_KEY_CHARS = 64
MAX_VALUE_CHARS = 1000


def stored_passthrough(raw: Any) -> Optional[Dict[str, Any]]:
    """Scalar passthrough values bounded for storage.

    Args:
        raw: The request's ``passthrough`` field.

    Returns:
        Up to ``MAX_KEYS`` entries with string keys and scalar values (strings
        cut to ``MAX_VALUE_CHARS``), or ``None`` when nothing is left.
    """
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    for key, value in raw.items():
        if len(out) >= MAX_KEYS:
            break
        if not isinstance(key, str) or not key.strip() or len(key) > MAX_KEY_CHARS:
            continue
        if isinstance(value, str):
            out[key] = value[:MAX_VALUE_CHARS]
        elif isinstance(value, float):
            # JSONB rejects NaN and infinity.
            if math.isfinite(value):
                out[key] = value
        elif value is None or isinstance(value, (bool, int)):
            out[key] = value
    return out or None
