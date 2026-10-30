"""The admin's default guardrails for new agents (Admin > Defaults).

One JSON value in ``app_metadata``, validated as a ``GuardrailsConfig`` on
write. It is copied into an agent's ``config.guardrails`` when the agent is
created, on every path that creates one (the builder, template adoption,
imports, a shared conversation's agent), overlaid by the guardrails fields the
creating request or copied agent sets. Existing agents are never changed by
it. With nothing stored, new agents get exactly the config they always did.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import Connection

from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository

logger = logging.getLogger(__name__)

#: ``app_metadata`` key of the stored default ``guardrails`` object.
KEY = "agents.default_guardrails"


def stored(conn: Connection) -> Optional[dict]:
    """The stored default guardrails, normalised, or ``None`` when the admin has set none.

    Read leniently, as an agent's own config is: a control this instance no
    longer allows is dropped on its own.

    Args:
        conn: Database connection.
    """
    raw = AppMetadataRepository(conn).get(KEY)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except Exception:
        logger.warning("The stored agent defaults are not JSON; new agents use the built-in guardrails")
        return None
    if not isinstance(value, dict):
        return None
    return GuardrailsConfig.parse(value).model_dump(mode="json")


def load(conn: Connection) -> dict:
    """The default guardrails new agents start from: the stored ones, else the built-in defaults."""
    return stored(conn) or GuardrailsConfig().model_dump(mode="json")


def save(conn: Connection, guardrails: GuardrailsConfig) -> dict:
    """Store ``guardrails`` as the default for new agents and return it as stored."""
    value = guardrails.model_dump(mode="json")
    AppMetadataRepository(conn).set(KEY, json.dumps(value))
    return value


def seed(conn: Connection, config: Any) -> Any:
    """A new agent's ``config`` with the default guardrails under its own guardrails fields.

    The overlay is by key: every guardrails field the config sets wins (a
    ``controls`` list replaces the default list), the rest come from the
    defaults.

    Args:
        conn: Database connection.
        config: The ``config`` the new agent would get: a dict, its JSON text
            (as a form post sends it), or ``None``.

    Returns:
        ``config`` unchanged when no defaults are stored or it is not an object
        (validation then rejects it), else a new dict.
    """
    defaults = stored(conn)
    if defaults is None:
        return config
    parsed = config
    if isinstance(config, str):
        try:
            parsed = json.loads(config) if config.strip() else None
        except ValueError:
            return config
    if parsed is not None and not isinstance(parsed, dict):
        return config
    parsed = parsed or {}
    requested = parsed.get("guardrails")
    if requested is not None and not isinstance(requested, dict):
        return config
    return {**parsed, "guardrails": {**defaults, **(requested or {})}}
