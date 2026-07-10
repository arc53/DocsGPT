"""Migration round-trip test for 0022_source_config."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "application" / "alembic.ini"


def _run_alembic(url: str, *args: str) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), *args],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _alembic_version(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


_0022 = "0022_source_config"
_0021 = "0021_teams"


class TestMigration0022RoundTrip:
    def test_head_has_config_column(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0022
            assert _column_exists(conn, "sources", "config")

    def test_config_server_default_backfills_empty(self, pg_engine):
        with pg_engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO sources (user_id, name) "
                    "VALUES ('u-cfg', 's') RETURNING config"
                )
            ).fetchone()
            assert row[0] == {}

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0021)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0021
            assert not _column_exists(conn, "sources", "config")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0022
            assert _column_exists(conn, "sources", "config")
