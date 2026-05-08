"""Per-request connection helpers for route handlers.

Every route-handler that talks to Postgres opens a short-lived, explicit
transaction via the context managers in this module. The pattern is::

    from application.storage.db.session import db_session

    with db_session() as conn:
        repo = PromptsRepository(conn)
        prompt = repo.get(prompt_id, user_id)

Why explicit, not ``flask.g``: the lifecycle stays local to each handler,
which mirrors how the repository test fixtures already work and keeps
error handling obvious. Celery tasks and the seeder use the same helper
so there's one pattern to learn.

Two flavors:

* ``db_session()`` — opens a transaction (``engine.begin()``). Commits on
  clean exit, rolls back on exception. Use for any handler that may
  write.
* ``db_readonly()`` — opens a plain connection (``engine.connect()``) for
  read-only paths. Avoids the commit round-trip on pure reads.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection, text

from application.storage.db.engine import get_engine


@contextmanager
def db_session() -> Iterator[Connection]:
    """Transactional connection. Commits on success, rolls back on error."""
    with get_engine().begin() as conn:
        yield conn


@contextmanager
def db_readonly() -> Iterator[Connection]:
    """Read-only connection for handlers that never write.

    The connection is placed into a Postgres ``READ ONLY`` transaction
    before any caller statement runs, so an accidental ``INSERT`` /
    ``UPDATE`` / ``DELETE`` from inside the block raises
    ``InternalError: cannot execute ... in a read-only transaction``
    instead of silently mutating data.

    The transaction itself is rolled back on exit — a read-only
    transaction has nothing meaningful to commit, and rolling back avoids
    leaving the connection in an open-transaction state when it returns
    to the pool.
    """
    with get_engine().connect() as conn:
        trans = conn.begin()
        try:
            # Must be the first statement in the txn; psycopg3 + SA both
            # honor this and Postgres rejects writes for the rest of the
            # transaction's lifetime.
            conn.execute(text("SET TRANSACTION READ ONLY"))
            yield conn
        finally:
            trans.rollback()
