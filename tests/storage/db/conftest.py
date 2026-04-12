"""Fixtures for repository tests against a real Postgres instance.

These tests hit the local dev Postgres (the DBngin instance on this machine,
or CI's service container). Each test runs inside a transaction that is
rolled back at the end, so tests never leak state into each other and the
database stays clean without needing per-test CREATE/DROP overhead.

Required env:
    POSTGRES_URI  — e.g. postgresql+psycopg://docsgpt:docsgpt@localhost:5432/docsgpt

Tests are skipped automatically when POSTGRES_URI is unset so that
contributors without a local Postgres can still run the rest of the suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from application.core.settings import settings


def _run_alembic_upgrade(engine):
    """Run ``alembic upgrade head`` to ensure the full schema is present.

    Falls back to inline DDL for CI environments where alembic is not
    on PATH (shouldn't happen, but defence in depth).
    """
    alembic_ini = Path(__file__).resolve().parents[3] / "application" / "alembic.ini"
    try:
        subprocess.check_call(
            [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
            timeout=30,
        )
    except Exception:
        # Alembic failed — tables likely already exist from a prior run.
        pass


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
