"""JSON-safe coercion for PG-native Python types.

Postgres (via psycopg) returns native Python types — ``uuid.UUID``,
``datetime.datetime``/``datetime.date``, ``decimal.Decimal``, ``bytes``
— that ``json.dumps`` rejects. This module is the single place those
coercion rules live; everywhere else should call into it.

Two interfaces with identical coverage:

* :func:`coerce_pg_native` — recursive walk returning a JSON-safe copy.
  Use when you need to inspect the dict yourself or pass it to a
  serializer that doesn't accept a custom encoder (e.g. SQLAlchemy
  parameter binding for a JSONB column).
* :class:`PGNativeJSONEncoder` — ``JSONEncoder`` subclass. Use as
  ``json.dumps(obj, cls=PGNativeJSONEncoder)`` for serialise-once flows
  where the extra recursive walk is wasted work.

Coercion rules:

* ``UUID`` → canonical hex string.
* ``datetime`` / ``date`` → ISO 8601 string.
* ``Decimal`` → numeric string (preserves precision; ``float()`` would not).
* ``bytes`` → base64 string. Lossless and universally JSON-safe;
  prior code used UTF-8 with ``errors="replace"`` which silently
  corrupted binary payloads (e.g. Gemini's ``thought_signature``).
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _coerce_scalar(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return obj


def coerce_pg_native(obj: Any) -> Any:
    """Recursively coerce PG-native types to JSON-safe equivalents.

    Recurses into ``dict`` (stringifying keys, matching prior helper
    behavior) and ``list``/``tuple`` (tuples flatten to lists since JSON
    has no tuple type). Any other type passes through unchanged.
    """
    if isinstance(obj, dict):
        return {str(k): coerce_pg_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [coerce_pg_native(v) for v in obj]
    return _coerce_scalar(obj)


def decode_base64_bytes(value: Any) -> Any:
    """Reverse ``coerce_pg_native``'s bytes-to-base64 step.

    Useful at egress points that need the original bytes back (e.g.
    sending Gemini's ``thought_signature`` to the SDK on resume). Uses
    ``validate=True`` so plain ASCII strings that happen to be
    permissively decodable (e.g. ``"abcd"``) are not silently turned
    into bytes — the original value passes through.
    """
    if isinstance(value, str):
        try:
            return base64.b64decode(value.encode("ascii"), validate=True)
        except (binascii.Error, ValueError):
            return value
    return value


class PGNativeJSONEncoder(json.JSONEncoder):
    """``JSONEncoder`` covering UUID / datetime / date / Decimal / bytes.

    Use as ``json.dumps(obj, cls=PGNativeJSONEncoder)``. Equivalent in
    coverage to :func:`coerce_pg_native` but skips the eager walk.
    """

    def default(self, obj: Any) -> Any:
        coerced = _coerce_scalar(obj)
        if coerced is obj:
            return super().default(obj)
        return coerced
