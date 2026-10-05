"""Bounded, secret-redacted content previews stored with a trace span."""

from __future__ import annotations

import json
from typing import Any

from docsgpt.core.settings import settings
from docsgpt.storage.db.redaction import redact_secrets
from docsgpt.utils import strip_null_bytes

_ELLIPSIS = "…"
# A list longer than this keeps its head only; the preview is for reading,
# not for reconstructing the payload.
_MAX_LIST_ITEMS = 50


def _bound(value: Any, limit: int) -> Any:
    """Truncate strings and long lists inside ``value``; stringify unknown objects."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + _ELLIPSIS
    if isinstance(value, dict):
        return {str(k): _bound(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_bound(v, limit) for v in list(value)[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            items.append(f"{_ELLIPSIS} {len(value) - _MAX_LIST_ITEMS} more")
        return items
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bound(str(value), limit)


def make_preview(value: Any, limit: int | None = None) -> Any:
    """Return a storable preview of ``value``.

    Secret-keyed fields are redacted, NUL bytes stripped and every string
    truncated to ``limit`` (``TRACES_PREVIEW_CHARS`` by default). A structure
    whose JSON form is still far larger than ``limit`` collapses to a
    truncated JSON string so one huge tool result cannot bloat the row.

    Args:
        value: Any JSON-like value (tool arguments, a result, a query string).
        limit: Maximum characters per string; defaults to the setting.

    Returns:
        A JSON-serializable preview.
    """
    limit = limit or settings.TRACES_PREVIEW_CHARS
    bounded = strip_null_bytes(_bound(redact_secrets(value), limit))
    if isinstance(bounded, (dict, list)):
        try:
            encoded = json.dumps(bounded, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            encoded = str(bounded)
        if len(encoded) > limit * 4:
            return encoded[:limit] + _ELLIPSIS
    return bounded
