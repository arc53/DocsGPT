"""What a paired device's client says it can do, from its ``X-Device-Capabilities`` header.

docsgpt-cli sends ``X-Device-Capabilities: cancel,outbox`` on every request:

* ``cancel``: it stops a running command on ``event: cancel`` and reports
  ``error: "cancelled"``;
* ``outbox``: it keeps a command's report until the server accepts it and
  resends it after a network failure, numbering every chunk (``seq``), so
  the server must drop chunks it already has.

A client without the header can do neither. The value is stored on the device
row each time the device authenticates, so the server knows what the running
client can do, not what an earlier version could.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

HEADER = "X-Device-Capabilities"

CANCEL = "cancel"
OUTBOX = "outbox"

_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")

#: Most capabilities kept from one header.
_MAX_TOKENS = 16


def parse(value: Optional[str]) -> str:
    """A capabilities header as a normalized, sorted comma list ("" for none or junk)."""
    tokens = set()
    for part in str(value or "").split(","):
        token = part.strip().lower()
        if _TOKEN.match(token):
            tokens.add(token)
    return ",".join(sorted(tokens)[:_MAX_TOKENS])


def from_headers(headers: Mapping[str, Any]) -> str:
    """The normalized capabilities a request's headers carry."""
    getter = getattr(headers, "get", None)
    raw = getter(HEADER) if callable(getter) else None
    if raw is None:
        lowered = HEADER.lower()
        raw = next((v for k, v in headers.items() if str(k).lower() == lowered), None)
    return parse(raw)


def has(capabilities: Optional[str], capability: str) -> bool:
    """Whether a stored or parsed capabilities list includes ``capability``."""
    return capability in str(capabilities or "").split(",")
