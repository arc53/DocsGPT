"""Migration round-trip test for 0042_schedule_created_via_api."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


pytestmark = pytest.mark.integration

_0041 = "0041_connection_account_name"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _insert(conn, created_via: str) -> None:
    conn.execute(
        text(
            "INSERT INTO schedules (user_id, trigger_type, instruction, run_at, next_run_at, created_via) "
            "VALUES ('u', 'once', 'x', now(), now(), :v)"
        ),
        {"v": created_via},
    )


class TestMigration0042RoundTrip:
    def test_head_accepts_api(self, pg_engine):
        with pg_engine.begin() as conn:
            _insert(conn, "api")

    def test_downgrade_folds_api_into_chat_then_upgrade_restores(self, pg_engine):
        with pg_engine.begin() as conn:
            _insert(conn, "api")
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0041)
        with pg_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM schedules WHERE created_via = 'api'")).scalar() == 0
        with pytest.raises(IntegrityError), pg_engine.begin() as conn:
            _insert(conn, "api")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.begin() as conn:
            _insert(conn, "api")
