"""Alembic environment for the DocsGPT user-data Postgres database.

The URL is pulled from ``application.core.settings`` rather than
``alembic.ini`` so that a single ``POSTGRES_URI`` env var drives both the
running app and ``alembic`` CLI invocations.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

# Make the project root importable regardless of cwd. env.py lives at
# <repo>/application/alembic/env.py, so parents[2] is the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from alembic import context  # noqa: E402
from sqlalchemy import engine_from_config, pool  # noqa: E402

from application.core.settings import settings  # noqa: E402
from application.storage.db.models import metadata as target_metadata  # noqa: E402

config = context.config

# Populate the runtime URL from settings.
if settings.POSTGRES_URI:
    config.set_main_option("sqlalchemy.url", settings.POSTGRES_URI)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


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
