"""Migration round-trip test for 0053_workflow_run_progress."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0052 = "0052_connector_oauth_flows"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _has_progress(conn) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'workflow_runs' AND column_name = 'progress'"
            )
        ).scalar()
    )


class TestMigration0053:
    def test_round_trip(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.connect() as conn:
            assert _has_progress(conn)
        _run_alembic(url, "downgrade", _0052)
        with pg_engine.connect() as conn:
            assert not _has_progress(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _has_progress(conn)
