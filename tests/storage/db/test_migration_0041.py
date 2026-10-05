"""Migration round-trip test for 0041_connection_account_name."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0039 = "0041_connection_account_name"
_0038 = "0040_connections"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _has_column(conn) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'connector_sessions' AND column_name = 'account_name'"
        )
    ).fetchone() is not None


class TestMigration0041RoundTrip:
    def test_head_has_account_name(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _has_column(conn)

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0038)
        with pg_engine.connect() as conn:
            assert not _has_column(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _has_column(conn)
