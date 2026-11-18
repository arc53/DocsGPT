"""Migration round-trip test for 0054_decision_usage."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


pytestmark = pytest.mark.integration

_0053 = "0053_workflow_run_progress"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _row(conn, status: str = "ok") -> None:
    conn.execute(
        text(
            "INSERT INTO decision_usage (day, feature, mode, status, calls, states, answered) "
            "VALUES (CURRENT_DATE, 'injection_input', 'local', :status, 1, 1, 1)"
        ),
        {"status": status},
    )


def _has_table(conn) -> bool:
    return conn.execute(text("SELECT to_regclass('public.decision_usage')")).scalar() is not None


class TestMigration0054RoundTrip:
    def test_head_keys_a_row_by_day_feature_mode_version_and_status(self, pg_engine):
        with pg_engine.begin() as conn:
            _row(conn)
            _row(conn, status="timeout")
            row = conn.execute(text("SELECT model_version, ms_total, queue_ms_total FROM decision_usage LIMIT 1")).one()
            assert tuple(row) == ("", 0.0, 0.0)
        with pytest.raises(IntegrityError, match="decision_usage_pkey"):
            with pg_engine.begin() as conn:
                _row(conn)

    def test_downgrade_drops_the_table(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            _row(conn)
        _run_alembic(url, "downgrade", _0053)
        with pg_engine.connect() as conn:
            assert not _has_table(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _has_table(conn)
