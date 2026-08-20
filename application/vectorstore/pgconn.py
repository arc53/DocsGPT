"""Process-wide psycopg connection pools keyed by DSN.

Every component that talks to the pgvector database — the vector store and the
GraphRAG graph store — checks out of the *same* pool for a given DSN, so a
request that touches N sources costs pooled checkouts instead of N fresh TCP +
TLS + auth handshakes. Keeping the registry in its own module (rather than in
``pgvector``) is what lets ``application.graphrag.store`` join it without
importing the vector store.

The boot-time schema hook deliberately does not use this: pools are built
lazily on first checkout, i.e. after the fork in a Celery/gunicorn worker, so a
preloading parent never hands a live socket to a child.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict

# Seconds a caller waits for a free pooled connection before giving up.
POOL_TIMEOUT_SECONDS = 30.0

# Physical connections one process may hold per DSN. Lives here, not in either
# store: ``pool_for`` keys its registry by DSN and applies ``max_size`` only on
# creation, so two stores disagreeing about the default would make the
# effective pool size depend on which of them touched the DSN first.
DEFAULT_POOL_MAX_SIZE = 8

# dsn -> psycopg_pool.ConnectionPool, one per process.
_POOLS: Dict[str, Any] = {}
_POOLS_LOCK = threading.Lock()


def configure_pooled_connection(conn) -> None:
    """Register pgvector's type adapters once per physical pooled connection.

    Tolerates a database where ``CREATE EXTENSION vector`` has not run yet:
    ``register_vector`` looks the type up in the catalog and raises when it is
    absent, which would leave the pool unable to open the very connection the
    schema bootstrap needs. The write path re-registers once the type exists.
    """
    from pgvector.psycopg import register_vector

    try:
        register_vector(conn)
    except Exception as e:
        logging.debug("pgvector types not registered yet: %s", e)


def resolve_pool_max_size() -> int:
    """Pool size from settings, defensively — 0 means one direct connection.

    Returns:
        int: ``PGVECTOR_POOL_MAX_SIZE`` when it is a non-negative, non-bool
        int, else :data:`DEFAULT_POOL_MAX_SIZE`. The unit suite replaces
        ``settings`` with a MagicMock, whose attributes must never become
        a pool size.
    """
    from application.core.settings import settings

    value = getattr(settings, "PGVECTOR_POOL_MAX_SIZE", DEFAULT_POOL_MAX_SIZE)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return DEFAULT_POOL_MAX_SIZE


def pool_for(dsn: str, max_size: int):
    """Return this process's connection pool for ``dsn``, creating it lazily.

    The pool is keyed by DSN alone and is built on first checkout — i.e. after
    the fork in a Celery/gunicorn worker, so a preloading parent never hands a
    live socket to a child. The boot-time schema hook must therefore use a
    direct connection rather than this pool.

    Args:
        dsn: libpq connection string; the pool's only identity.
        max_size: Upper bound on physical connections, used on creation only.

    Returns:
        psycopg_pool.ConnectionPool: The shared pool for ``dsn``.
    """
    pool = _POOLS.get(dsn)
    if pool is not None:
        return pool
    with _POOLS_LOCK:
        pool = _POOLS.get(dsn)
        if pool is None:
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                conninfo=dsn,
                min_size=1,
                max_size=max_size,
                open=True,
                timeout=POOL_TIMEOUT_SECONDS,
                name="docsgpt-pgvector",
                configure=configure_pooled_connection,
                check=ConnectionPool.check_connection,
            )
            _POOLS[dsn] = pool
    return pool


def release(dsn: str, conn, pooled: bool) -> None:
    """Hand ``conn`` back: to ``dsn``'s pool when pooled, else close it.

    A pooled connection is rolled back first when it is still in a transaction,
    so the next borrower gets a clean session. Never raises — releasing is
    always best-effort cleanup on a path that is often a destructor.

    Args:
        dsn: Connection string the connection was opened for.
        conn: The psycopg connection being released; ``None`` is a no-op.
        pooled: Whether the connection came from :func:`pool_for`.
    """
    if conn is None:
        return
    try:
        if pooled:
            try:
                if conn.info.transaction_status.name != "IDLE":
                    conn.rollback()
            except Exception:
                # Connection already broken; the pool discards it.
                pass
            pool = _POOLS.get(dsn)
            if pool is not None:
                pool.putconn(conn)
            elif not conn.closed:
                conn.close()
        elif not conn.closed:
            conn.close()
    except Exception as e:
        logging.debug("Error releasing pooled connection: %s", e)
