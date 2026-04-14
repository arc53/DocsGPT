"""Fixtures for **integration / e2e** repository tests against a real Postgres instance.

These tests are intentionally distinct from the rest of the suite:

* The root ``tests/conftest.py`` provides a ``pg_conn`` fixture backed by
  ``pytest-postgresql`` that spawns its own ephemeral cluster. That is
  the fixture used by unit tests that talk to the repositories.
* The fixtures *in this file* override ``pg_engine`` / ``pg_conn`` for
  tests under ``tests/storage/db/`` only, pointing at a real,
  long-running Postgres (DBngin locally, a service container in CI).
  Every test file here is marked ``@pytest.mark.integration``.

Why the distinction: repository integration tests exercise real SQL
against real schema state and can surface driver/dialect issues that an
ephemeral, Alembic-migrated-from-scratch cluster would also exercise —
but we want them to run against a DB that more closely mirrors the
production Postgres setup (connection pooling, extensions, role/grants).
They are opt-in via ``POSTGRES_URI`` so that contributors without a
local Postgres can still run the rest of the suite.

Required env:
    POSTGRES_URI  — e.g. postgresql+psycopg://docsgpt:docsgpt@localhost:5432/docsgpt

Each test runs inside a transaction that is rolled back at the end, so
tests never leak state into each other and the database stays clean
without needing per-test CREATE/DROP overhead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from application.core.settings import settings


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test under ``tests/storage/db/`` as ``integration``.

    Saves each test file from having to repeat the marker manually.
    """
    for item in items:
        if "tests/storage/db/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


def _run_alembic_upgrade(engine):
    """Run ``alembic upgrade head`` to ensure the full schema is present.

    Non-zero exit is re-raised so genuine schema-drift bugs surface as
    test failures. If alembic reports the schema is already at head,
    the subprocess still exits zero.
    """
    alembic_ini = Path(__file__).resolve().parents[3] / "application" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
        timeout=60,
    )


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped engine pointing at the test Postgres."""
    if not settings.POSTGRES_URI:
        pytest.skip("POSTGRES_URI not set")
    engine = create_engine(settings.POSTGRES_URI)
    _run_alembic_upgrade(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_conn(pg_engine):
    """Per-test connection wrapped in a transaction that always rolls back.

    Repositories receive this connection and operate normally. At teardown
    the outer transaction is rolled back so no data persists between tests.
    """
    conn = pg_engine.connect()
    txn = conn.begin()
    yield conn
    txn.rollback()
    conn.close()
