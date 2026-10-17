"""The admin's default settings for new sources (Admin > Defaults): retrieval and guardrails.

Two JSON values in ``app_metadata``, validated as a ``RetrievalConfig`` and a
``SourceGuardrailsConfig`` on write. They are copied into a source when the
source is created, each overlaid by the fields of its section the creating
request sent; existing sources are never changed by them. With nothing stored,
new sources get the built-in defaults exactly as before, and nothing extra is
written to their row.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import Connection

from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.storage.db.source_config import RetrievalConfig, SourceGuardrailsConfig

logger = logging.getLogger(__name__)

#: ``app_metadata`` key of the stored default ``retrieval`` object.
KEY = "sources.default_retrieval"
#: ``app_metadata`` key of the stored default ``guardrails`` object.
GUARDRAILS_KEY = "sources.default_guardrails"


def stored(conn: Connection) -> Optional[dict]:
    """The stored default ``retrieval``, normalised, or ``None`` when the admin has set none.

    A value this version cannot read (written by another one) counts as none.

    Args:
        conn: Database connection.
    """
    raw = AppMetadataRepository(conn).get(KEY)
    if not raw:
        return None
    try:
        return RetrievalConfig.model_validate(json.loads(raw)).model_dump()
    except Exception:
        logger.warning("The stored source defaults do not validate; new sources use the built-in ones")
        return None


def load(conn: Connection) -> dict:
    """The default ``retrieval`` new sources start from: the stored one, else the built-in defaults."""
    return stored(conn) or RetrievalConfig().model_dump()


def save(conn: Connection, retrieval: RetrievalConfig) -> dict:
    """Store ``retrieval`` as the default for new sources and return it as stored."""
    value = retrieval.model_dump()
    AppMetadataRepository(conn).set(KEY, json.dumps(value))
    return value


def stored_guardrails(conn: Connection) -> Optional[dict]:
    """The stored default ``guardrails``, normalised, or ``None`` when the admin has set none.

    Args:
        conn: Database connection.
    """
    raw = AppMetadataRepository(conn).get(GUARDRAILS_KEY)
    if not raw:
        return None
    try:
        return SourceGuardrailsConfig.model_validate(json.loads(raw)).model_dump()
    except Exception:
        logger.warning("The stored source guardrails defaults do not validate; new sources use the built-in ones")
        return None


def load_guardrails(conn: Connection) -> dict:
    """The default ``guardrails`` new sources start from: the stored one, else the built-in defaults."""
    return stored_guardrails(conn) or SourceGuardrailsConfig().model_dump()


def save_guardrails(conn: Connection, guardrails: SourceGuardrailsConfig) -> dict:
    """Store ``guardrails`` as the default for new sources and return it as stored."""
    value = guardrails.model_dump()
    AppMetadataRepository(conn).set(GUARDRAILS_KEY, json.dumps(value))
    return value


def seed(conn: Connection, config: Optional[dict]) -> Optional[dict]:
    """A new source's ``config`` with the default ``retrieval`` and ``guardrails`` under the request's own fields.

    Each section is overlaid by key: every field of it the request sent wins,
    the rest come from the defaults. A request that turns on relevance
    (``reranker``) or LLM screening (``prescreen``) without naming the other
    also drops the default's other one, since a source cannot have both.

    Args:
        conn: Database connection.
        config: The ``config`` the creating request sent, or ``None``.

    Returns:
        ``config`` unchanged when no defaults are stored (or a section it sent
        is not an object, which validation then rejects), else a new dict.
    """
    seeded = config
    defaults = stored(conn)
    requested = (config or {}).get("retrieval")
    if defaults is not None and (requested is None or isinstance(requested, dict)):
        requested = requested or {}
        if requested.get("prescreen") is not None and "reranker" not in requested:
            defaults["reranker"] = None
        if requested.get("reranker") is not None and "prescreen" not in requested:
            defaults["prescreen"] = None
        seeded = {**(seeded or {}), "retrieval": {**defaults, **requested}}
    guardrails = stored_guardrails(conn)
    requested = (config or {}).get("guardrails")
    if guardrails is not None and (requested is None or isinstance(requested, dict)):
        seeded = {**(seeded or {}), "guardrails": {**guardrails, **(requested or {})}}
    return seeded


def seed_new(config: Optional[dict]) -> Optional[dict]:
    """``seed`` on a connection of its own, for a route that validates the request before any write."""
    with db_readonly() as conn:
        return seed(conn, config)
