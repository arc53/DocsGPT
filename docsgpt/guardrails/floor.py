"""The instance floor and the other guardrail settings an admin edits in Admin > Guardrails.

Both live in ``app_metadata``. The floor is the ``GuardrailsConfig`` fragment
every agent inherits and cannot weaken (``runtime.merge_floor``), validated on
write as ``GUARDRAILS_FLOOR`` was. Every agent turn reads it, so it goes
through a small per-process cache: a write replaces it in the writing process,
and every other process (API workers, Celery workers) picks the change up
within ``TTL_SECONDS``. A read that fails keeps the last floor read, so a
database hiccup never drops the floor.

``GUARDRAILS_FLOOR`` shipped in 1.0.0. It is read only by ``import_env_floor``,
once at start: with no floor stored, its value is stored; afterwards the stored
floor wins and the env value is ignored, with a warning either way.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

from sqlalchemy import Connection

from docsgpt.core.settings import settings
from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

#: ``app_metadata`` key of the floor; a stored ``null`` is an admin's "no floor", which keeps the env value from
#: being imported again.
KEY = "guardrails.floor"
#: ``app_metadata`` key of the MCP tool-description warnings toggle.
MCP_WARNINGS_KEY = "guardrails.mcp_description_warnings"
#: Seconds a process trusts the floor it read before reading it again.
TTL_SECONDS = 30.0

_lock = threading.Lock()
_floor: Optional[GuardrailsConfig] = None
_expires = 0.0


def _parse(raw: Optional[str]) -> Optional[GuardrailsConfig]:
    """The stored floor as a config, or ``None`` when there is none or it applies to nothing.

    Lenient like an agent's config: a control that stopped validating (its
    check disallowed by ``GUARDRAILS_CHECKS_ENABLED``) is dropped on its own
    rather than taking the whole floor with it.
    """
    value = json.loads(raw) if raw else None
    if not value:
        return None
    floor = GuardrailsConfig.parse(value)
    return floor if floor.enabled else None


def stored(conn: Connection) -> Optional[dict]:
    """The stored floor as the admin saved it, or ``None`` when none is stored or it was cleared.

    Args:
        conn: Database connection.
    """
    raw = AppMetadataRepository(conn).get(KEY)
    value = json.loads(raw) if raw else None
    return value or None


def save(conn: Connection, floor: Optional[GuardrailsConfig]) -> Optional[dict]:
    """Store ``floor`` (``None`` clears it) and return it as stored.

    The caller invalidates the cache once the transaction commits.

    Args:
        conn: Database connection.
        floor: The validated floor, or ``None`` for no floor.
    """
    value = floor.model_dump(mode="json") if floor is not None else None
    AppMetadataRepository(conn).set(KEY, json.dumps(value))
    return value


def invalidate() -> None:
    """Make the next ``current()`` in this process read the floor again."""
    global _expires
    with _lock:
        _expires = 0.0


def current() -> Optional[GuardrailsConfig]:
    """The floor every agent follows, through the per-process cache; ``None`` when there is none.

    A read that fails keeps the floor last read for another ``TTL_SECONDS``,
    so a database outage neither drops the floor nor retries on every turn.
    """
    global _floor, _expires
    now = time.monotonic()
    with _lock:
        if now < _expires:
            return _floor
    try:
        with db_readonly() as conn:
            floor = _parse(AppMetadataRepository(conn).get(KEY))
    except Exception:
        logger.warning("Could not read the guardrails floor; agents keep the floor last read", exc_info=True)
        with _lock:
            _expires = now + TTL_SECONDS
            return _floor
    with _lock:
        _floor, _expires = floor, now + TTL_SECONDS
        return floor


def import_env_floor(log: Optional[logging.Logger] = None) -> None:
    """Store ``GUARDRAILS_FLOOR`` as the floor once, when it is set and no floor is stored.

    Called at start, after the migrations. An invalid env value is not stored.
    Never raises: the database being unreachable leaves the import to the next
    start.

    Args:
        log: Logger for the deprecation warnings; module logger when omitted.
    """
    out = log or logger
    raw = settings.GUARDRAILS_FLOOR
    if not raw:
        return
    try:
        with db_session() as conn:
            repo = AppMetadataRepository(conn)
            if repo.get(KEY) is not None:
                out.warning(
                    "GUARDRAILS_FLOOR is deprecated and ignored: the floor stored in Admin > Guardrails applies. "
                    "Remove GUARDRAILS_FLOOR from the environment."
                )
                return
            try:
                floor = GuardrailsConfig.model_validate(raw)
            except Exception:
                out.error("GUARDRAILS_FLOOR is invalid and was not imported; set the floor in Admin > Guardrails")
                return
            repo.setdefault(KEY, json.dumps(floor.model_dump(mode="json")))
    except Exception as exc:  # noqa: BLE001 - never block boot on the database
        out.warning("Could not import GUARDRAILS_FLOOR (%s); it is retried at the next start", exc)
        return
    invalidate()
    out.warning(
        "GUARDRAILS_FLOOR is deprecated: its value was imported as the floor every agent follows, now edited in "
        "Admin > Guardrails. Remove GUARDRAILS_FLOOR from the environment; it is ignored from now on."
    )
    if not floor.enabled:
        out.warning('The imported floor has "enabled": false, so it applies to nothing until it is enabled')


def mcp_description_warnings(conn: Connection) -> bool:
    """Whether Admin > Guardrails turned on warnings for MCP tool descriptions (off unless stored).

    Args:
        conn: Database connection.
    """
    return AppMetadataRepository(conn).get(MCP_WARNINGS_KEY) == "true"


def set_mcp_description_warnings(conn: Connection, on: bool) -> None:
    """Store the MCP tool-description warnings toggle.

    Args:
        conn: Database connection.
        on: Whether to warn.
    """
    AppMetadataRepository(conn).set(MCP_WARNINGS_KEY, "true" if on else "false")
