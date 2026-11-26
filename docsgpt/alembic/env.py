"""Alembic environment for the DocsGPT user-data Postgres database.

The URL is pulled from ``docsgpt.core.settings`` rather than
``alembic.ini`` so that a single ``POSTGRES_URI`` env var drives both the
running app and ``alembic`` CLI invocations.
"""

import logging
import sys
import time
from logging.config import fileConfig
from pathlib import Path

# Make the project root importable regardless of cwd. env.py lives at
# <repo>/docsgpt/alembic/env.py, so parents[2] is the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from alembic import context  # noqa: E402
from sqlalchemy import engine_from_config, pool, text  # noqa: E402

from docsgpt.core.settings import settings  # noqa: E402
from docsgpt.storage.db.models import metadata as target_metadata  # noqa: E402

config = context.config

MIGRATION_LOCK_KEY = "docsgpt:alembic-upgrade"
MIGRATION_LOCK_POLL = 0.5

# Populate the runtime URL from settings.
if settings.POSTGRES_URI:
    config.set_main_option("sqlalchemy.url", settings.POSTGRES_URI)

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    # ``fileConfig`` reconfigures the ROOT logger from ``[logger_root]``
    # (level WARNING, a stderr handler), which drops every ``docsgpt.*``
    # INFO record, detaches the OTLP handler and the request/trace filter that
    # ``setup_logging()`` installed, and cannot be undone by
    # ``disable_existing_loggers=False`` — that flag only governs whether
    # existing loggers are switched off. ``app.py`` calls ``setup_logging()``
    # before ``ensure_database_ready()``, so an in-process migration would
    # silence the web tier for the life of the process, on exactly the boot
    # where a schema upgrade happened. In-process callers opt out via
    # ``cfg.attributes``; the alembic CLI still gets its configured logging.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _hold_migration_lock(connection) -> None:
    """Take the session-level migration lock, waiting while another process migrates.

    The API and the worker boot together and both migrate. Unserialised, two of them on an empty
    database each create ``alembic_version`` and one dies on a unique violation. The lock is a
    session one because migrations that build indexes concurrently commit midway. It is polled
    rather than waited for: a blocked ``pg_advisory_lock`` holds a snapshot, and
    ``CREATE INDEX CONCURRENTLY`` in the holder waits for every older snapshot, a deadlock. Once
    in, the waiter reads the committed revision and finds nothing left to do. NullPool closes the
    session on exit, which releases the lock even when a migration fails.
    """
    waiting = False
    while True:
        held = connection.execute(text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": MIGRATION_LOCK_KEY})
        acquired = held.scalar()
        connection.commit()
        if acquired:
            return
        if not waiting:
            logging.getLogger("alembic.env").info("Another process is migrating this database; waiting for it.")
            waiting = True
        time.sleep(MIGRATION_LOCK_POLL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL without a live DB)."""
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "POSTGRES_URI is not configured. Set it in your .env to a "
            "psycopg3 URI such as "
            "'postgresql+psycopg://user:pass@host:5432/docsgpt'."
        )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    if not config.get_main_option("sqlalchemy.url"):
        raise RuntimeError(
            "POSTGRES_URI is not configured. Set it in your .env to a "
            "psycopg3 URI such as "
            "'postgresql+psycopg://user:pass@host:5432/docsgpt'."
        )
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        _hold_migration_lock(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
