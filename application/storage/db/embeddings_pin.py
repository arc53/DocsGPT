"""The embedding model an installation is pinned to.

``EMBEDDINGS_NAME`` has a code-level default, and moving that default would
re-point an existing index at a different vector space without anything
noticing: mpnet and granite are both 768-dimensional, so no width check fires
and retrieval simply gets worse. Which model an index was built with is a
property of the installation, not of the release it happens to be running.

So it is resolved once at boot and stored in ``app_metadata``. A fresh install
is pinned to the current recommendation; an install that already has sources is
pinned to the legacy model it has been using all along, and told how to move.
An explicit ``EMBEDDINGS_NAME`` in the environment always wins over both.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

from application.core.settings import settings
from application.storage.db.repositories.app_metadata import AppMetadataRepository
from application.storage.db.session import db_session
from application.vectorstore.model_registry import (
    DEFAULT_LEGACY,
    DEFAULT_NEW_INSTALL,
    resolve,
)

logger = logging.getLogger(__name__)

PIN_KEY = "embeddings_name"
NOTICE_KEY = "embeddings_legacy_notice_shown"


def _has_sources(conn) -> bool:
    """True when this installation already has an index to protect.

    Counts ``sources`` rather than vector rows so the answer is the same for
    every vector store, including the FAISS ones whose vectors are not in this
    database at all.
    """
    if conn.execute(text("SELECT to_regclass('public.sources')")).scalar() is None:
        return False
    return bool(conn.execute(text("SELECT EXISTS (SELECT 1 FROM sources)")).scalar())


def _legacy_notice(model: str) -> str:
    return (
        f"Embeddings: this installation is using {model}, the model its index was "
        "built with, and will keep using it.\n"
        "To move to granite (multilingual, a 32k-token context, same 768 dimensions):\n"
        "  1. EMBEDDINGS_NAME=ibm-granite/granite-embedding-311m-multilingual-r2\n"
        "  2. python -m application.scripts.reembed\n"
        "Changing the model without step 2 leaves queries searching a different "
        "vector space than the stored vectors, which fails silently."
    )


def resolve_embeddings_pin(log: Optional[logging.Logger] = None) -> None:
    """Point ``settings.EMBEDDINGS_NAME`` at this installation's pinned model.

    Called once at boot, before anything embeds and before the vector schema
    hook reads the width. Consumers read ``settings.EMBEDDINGS_NAME`` lazily, so
    assigning it here is enough; no caller needs to know the pin exists.

    Does nothing when the environment pins the name, and degrades to the
    code-level default when the database cannot be reached.

    Args:
        log: Logger for the first-run notice; module logger when omitted.
    """
    out = log or logger
    if "EMBEDDINGS_NAME" in settings.model_fields_set:
        return

    try:
        with db_session() as conn:
            repo = AppMetadataRepository(conn)
            stored = repo.get(PIN_KEY)
            if stored:
                settings.EMBEDDINGS_NAME = stored
                return

            upgrading = _has_sources(conn)
            pinned = repo.setdefault(
                PIN_KEY, DEFAULT_LEGACY if upgrading else DEFAULT_NEW_INSTALL
            )
            settings.EMBEDDINGS_NAME = pinned
            out.info("Embeddings: pinned this installation to %s.", pinned)
            if upgrading and repo.get(NOTICE_KEY) is None:
                print(_legacy_notice(pinned), flush=True)
                repo.set(NOTICE_KEY, "1")
    except Exception as exc:  # noqa: BLE001 — never block boot on the database
        out.debug(
            "Embeddings: could not resolve the pinned model (%s); using %s.",
            exc,
            settings.EMBEDDINGS_NAME,
            exc_info=True,
        )


def warn_on_source_model_mismatch(log: Optional[logging.Logger] = None) -> None:
    """Report sources whose vectors were built by a different model.

    The width check cannot see this: mpnet and granite are both 768, so an
    index queried by the wrong model returns worse answers and no error. This
    is the only signal, so it names the sources and the command that fixes
    them.

    A source with no recorded model pre-dates the column and is therefore the
    legacy model, not unknown.

    Args:
        log: Logger to warn on; module logger when omitted.
    """
    out = log or logger
    active = resolve(settings.EMBEDDINGS_NAME)
    try:
        with db_session() as conn:
            if conn.execute(text("SELECT to_regclass('public.sources')")).scalar() is None:
                return
            rows = conn.execute(
                text("SELECT COALESCE(model, :legacy) AS model, count(*) FROM sources GROUP BY 1"),
                {"legacy": DEFAULT_LEGACY},
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 — never block boot on the database
        out.debug("Embeddings: could not check source models (%s)", exc, exc_info=True)
        return

    stale = [
        (name, count)
        for name, count in rows
        # Compare through the registry so an alias is not read as a different
        # model. An unregistered name resolves to None, which only matches
        # another unregistered name if the strings agree.
        for a, b in [(resolve(name), active)]
        if (a or name) != (b or settings.EMBEDDINGS_NAME)
    ]
    if not stale:
        return
    detail = ", ".join(f"{count} built with {name}" for name, count in stale)
    out.warning(
        "Embeddings: %s, but queries are embedded with %s. Retrieval against those "
        "sources is degraded and will not raise. Re-embed them with "
        "`python -m application.scripts.reembed`, or set EMBEDDINGS_NAME back.",
        detail,
        settings.EMBEDDINGS_NAME,
    )
