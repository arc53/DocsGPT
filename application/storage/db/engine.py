"""SQLAlchemy Core engine factory for the user-data Postgres database.

The engine is lazily constructed on first use and cached as a module-level
singleton. Repositories and the Alembic env module both obtain connections
through this factory, so pool tuning lives in one place.

``POSTGRES_URI`` can be written in any of the common Postgres URI forms::

    postgres://user:pass@host:5432/docsgpt
    postgresql://user:pass@host:5432/docsgpt

Both are accepted and normalized internally to the psycopg3 dialect
(``postgresql+psycopg://``) by ``application.core.settings``. Operators
don't need to know about SQLAlchemy dialect prefixes.
"""

from typing import Optional

from sqlalchemy import Engine, create_engine

from application.core.settings import settings

_engine: Optional[Engine] = None


def _resolve_uri() -> str:
    """Return the Postgres URI for user-data tables.

    Raises:
        RuntimeError: If ``settings.POSTGRES_URI`` is unset. Callers that
            reach this path without a configured URI have a setup bug — the
            error message points them at the right setting.
    """
    if not settings.POSTGRES_URI:
        raise RuntimeError(
            "POSTGRES_URI is not configured. Set it in your .env to a "
            "psycopg3 URI such as "
            "'postgresql+psycopg://user:pass@host:5432/docsgpt'."
        )
    return settings.POSTGRES_URI


#: Per-statement wall-clock cap applied to every connection handed out by
#: the engine. 30s is generous for interactive hot paths (reads under a few
#: hundred ms are normal) but still catches a runaway query before it
#: stacks up on PgBouncer or holds locks indefinitely. Override by
#: rebuilding the engine with a different ``connect_args`` in tests.
STATEMENT_TIMEOUT_MS = 30_000


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy Engine, creating it if needed.

    The engine applies a server-side ``statement_timeout`` to every
    connection it hands out, so both :func:`db_session` and
    :func:`db_readonly` inherit the same guardrail.

    Returns:
        A SQLAlchemy ``Engine`` configured with a pooled connection to
        Postgres via psycopg3.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(
            _resolve_uri(),
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,     # survive PgBouncer / idle-disconnect recycles
            pool_recycle=1800,
            future=True,
            connect_args={
                # ``-c`` passes a GUC to the backend at connect time. This
                # covers *all* sessions — interactive, Celery, seeder — so
                # no route-handler can opt out by accident.
                "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            },
        )
    return _engine


def dispose_engine() -> None:
    """Dispose the pooled connections and reset the singleton.

    Called from the Celery ``worker_process_init`` signal so each forked
    worker gets a fresh pool instead of sharing file descriptors with the
    parent process (which corrupts the pool on fork).
    """
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
