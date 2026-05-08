"""Per-activity logging context backed by ``contextvars``.

The ``_ContextFilter`` installed by ``logging_config.setup_logging`` stamps
every ``LogRecord`` emitted inside a ``bind`` block with the bound keys, so
they land as first-class attributes on the OTLP log export rather than being
buried inside formatted message bodies.

A single ``ContextVar`` holds a dict so nested binds reset atomically (LIFO)
via the token returned by ``bind``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Mapping


_CTX_KEYS: frozenset[str] = frozenset(
    {
        "activity_id",
        "parent_activity_id",
        "user_id",
        "agent_id",
        "conversation_id",
        "endpoint",
        "model",
    }
)

_ctx: ContextVar[Mapping[str, str]] = ContextVar("log_ctx", default={})


def bind(**kwargs: object) -> Token:
    """Overlay the given keys onto the current context.

    Returns a ``Token`` so the caller can ``reset`` in a ``finally`` block.
    Keys outside :data:`_CTX_KEYS` are silently dropped (so a typo can't
    stamp a stray field name onto every record), as are ``None`` values
    (a missing attribute is more useful than the literal string ``"None"``).
    """
    overlay = {
        k: str(v)
        for k, v in kwargs.items()
        if k in _CTX_KEYS and v is not None
    }
    new = {**_ctx.get(), **overlay}
    return _ctx.set(new)


def reset(token: Token) -> None:
    """Restore the context to the snapshot captured by the matching ``bind``."""
    _ctx.reset(token)


def snapshot() -> Mapping[str, str]:
    """Return the current context dict. Treat as read-only; use :func:`bind`."""
    return _ctx.get()
