"""Best-effort Postgres dual-write helper used during the MongoDB→Postgres
migration.

The helper:

* Returns immediately if ``settings.USE_POSTGRES`` is off, so default-off
  call sites add literally zero work.
* Opens a transactional connection from the user-data SQLAlchemy engine.
* Instantiates the caller's repository class on that connection.
* Runs the caller's operation.
* Swallows and logs any exception. **Mongo remains the source of truth
  during the dual-write window** — a Postgres-side failure must never
  break a user-facing request. Drift that builds up from swallowed
  failures is caught separately by re-running the backfill script.

Call sites look like::

    users_collection.update_one(..., {"$addToSet": {...}})             # Mongo write, unchanged
    dual_write(UsersRepository, lambda r: r.add_pinned(uid, aid))      # Postgres mirror

A single parameterised helper rather than one function per collection
means a new collection just needs its repository class — no new helper
function, no new feature flag. The whole helper is deleted at Phase 5
when the migration is complete.
"""

from __future__ import annotations

import logging
from typing import Callable, TypeVar

from application.core.settings import settings

logger = logging.getLogger(__name__)

_Repo = TypeVar("_Repo")


def dual_write(repo_cls: type[_Repo], fn: Callable[[_Repo], None]) -> None:
    """Mirror a Mongo write into Postgres via ``repo_cls``, best-effort.

    No-op when ``settings.USE_POSTGRES`` is false. Any exception
    (connection pool exhaustion, migration drift, SQL error) is logged
    and swallowed so the caller's primary Mongo write remains the source
    of truth.

    Args:
        repo_cls: The repository class to instantiate (e.g. ``UsersRepository``).
        fn: A callable that takes the instantiated repository and performs
            the desired write.
    """
    if not settings.USE_POSTGRES:
        return

    try:
        # Lazy import so modules that import dual_write don't pay the
        # SQLAlchemy import cost when the flag is off.
        from application.storage.db.engine import get_engine

        with get_engine().begin() as conn:
            fn(repo_cls(conn))
    except Exception:
        logger.warning(
            "Postgres dual-write failed for %s — Mongo write already committed",
            repo_cls.__name__,
            exc_info=True,
        )
