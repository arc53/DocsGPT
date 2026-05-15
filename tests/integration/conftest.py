"""Fixtures for integration tests that hit a live Postgres.

These tests are separate from unit tests in two ways:

1. **Directory**: They live under ``tests/integration/``, which is
   ignored by the default pytest run via ``--ignore=tests/integration``
   in ``pytest.ini``. The CI ``pytest.yml`` workflow therefore skips
   them automatically — it runs the fast unit suite only.
2. **Marker**: Each test is marked ``@pytest.mark.integration`` so it
   can be selected (or excluded) independently of its directory with
   ``pytest -m integration`` / ``-m "not integration"``.

Running the Postgres-backed integration tests manually::

    .venv/bin/python -m pytest tests/integration/test_users_repository.py \\
        --override-ini="addopts=" --no-cov

(The ``--override-ini="addopts="`` is needed because ``pytest.ini``
contains ``--ignore=tests/integration`` in ``addopts``; without the
override pytest would still skip the directory even though you named
it on the command line.)

Tests are skipped automatically if ``POSTGRES_URI`` is unset, so a
contributor who hasn't set up a local Postgres gets clean skips
instead of red tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, create_engine, text

from application.core.settings import settings


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    """Session-scoped SQLAlchemy engine for the Postgres integration DB.

    Skips all Postgres-backed tests if ``POSTGRES_URI`` is unset. This
    keeps CI and contributor machines without a local Postgres from
    erroring out — integration tests that require the DB become
    no-ops rather than failures.
    """
    if not settings.POSTGRES_URI:
        pytest.skip("POSTGRES_URI not set — skipping Postgres integration tests")
    engine = create_engine(settings.POSTGRES_URI, future=True, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pg_conn(pg_engine: Engine):
    """Per-test Postgres connection wrapped in a rolled-back transaction.

    Uses SQLAlchemy's explicit outer-transaction pattern so every test
    sees a pristine DB view without having to truncate tables. Any
    nested ``begin()`` inside the repository code becomes a SAVEPOINT
    under the hood.
    """
    conn = pg_engine.connect()
    outer = conn.begin()
    try:
        yield conn
    finally:
        outer.rollback()
        conn.close()


@pytest.fixture
def pg_clean_users(pg_conn):
    """Guarantee a clean ``users`` table view for tests that need it.

    The outer transaction rollback handles cleanup, but if a previous
    interrupted run left rows committed, this fixture removes them
    inside the transaction scope so they are invisible to the test.
    ``TRUNCATE CASCADE`` cascades through every FK to ``users`` (18
    tables and counting — agents, conversations, sources, user_logs,
    etc.) so the test view is clean regardless of which dependent rows
    a prior run left behind. PostgreSQL ``TRUNCATE`` is transactional,
    so the outer rollback still restores everything.
    """
    pg_conn.execute(text("TRUNCATE TABLE users CASCADE"))
    return pg_conn
