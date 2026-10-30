"""The admin's default retrieval settings for new sources (Admin > Defaults).

One JSON value in ``app_metadata``, validated as a ``RetrievalConfig`` on
write. It is copied into a source when the source is created, overlaid by the
retrieval fields the creating request sent; existing sources are never changed
by it. With nothing stored, new sources get the built-in ``RetrievalConfig``
defaults exactly as before, and nothing extra is written to their row.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import Connection

from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.storage.db.source_config import RetrievalConfig

logger = logging.getLogger(__name__)

#: ``app_metadata`` key of the stored default ``retrieval`` object.
KEY = "sources.default_retrieval"


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


def seed(conn: Connection, config: Optional[dict]) -> Optional[dict]:
    """A new source's ``config`` with the default ``retrieval`` under the request's own retrieval fields.

    The overlay is by key: every retrieval field the request sent wins, the
    rest come from the defaults. A request that turns on relevance
    (``reranker``) or LLM screening (``prescreen``) without naming the other
    also drops the default's other one, since a source cannot have both.

    Args:
        conn: Database connection.
        config: The ``config`` the creating request sent, or ``None``.

    Returns:
        ``config`` unchanged when no defaults are stored (or its ``retrieval``
        is not an object, which validation then rejects), else a new dict.
    """
    defaults = stored(conn)
    requested = (config or {}).get("retrieval")
    if defaults is None or (requested is not None and not isinstance(requested, dict)):
        return config
    requested = requested or {}
    if requested.get("prescreen") is not None and "reranker" not in requested:
        defaults["reranker"] = None
    if requested.get("reranker") is not None and "prescreen" not in requested:
        defaults["prescreen"] = None
    return {**(config or {}), "retrieval": {**defaults, **requested}}


def seed_new(config: Optional[dict]) -> Optional[dict]:
    """``seed`` on a connection of its own, for a route that validates the request before any write."""
    with db_readonly() as conn:
        return seed(conn, config)
