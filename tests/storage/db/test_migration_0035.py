"""Migration round-trip test for 0035_token_usage_latency."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"


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
            "WHERE table_name = :t AND column_name = :c AND table_schema = 'public'"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


_0035 = "0035_token_usage_latency"
_0034 = "0034_auth_events_actor_target"


class TestMigration0035RoundTrip:
    def test_head_has_latency_columns(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0035
            assert _column_exists(conn, "token_usage", "duration_ms")
            assert _column_exists(conn, "token_usage", "ttft_ms")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0034)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0034
            assert not _column_exists(conn, "token_usage", "duration_ms")
            assert not _column_exists(conn, "token_usage", "ttft_ms")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _column_exists(conn, "token_usage", "duration_ms")

    def test_existing_rows_read_null_latency(self, pg_engine):
        """Rows written before 0035 must read NULL, not 0 — a 0ms call is a lie."""
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0034)
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO token_usage (user_id, prompt_tokens, generated_tokens) "
                    "VALUES ('u-mig35', 10, 1)"
                )
            )
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT duration_ms, ttft_ms FROM token_usage "
                    "WHERE user_id = 'u-mig35'"
                )
            ).fetchone()
        assert tuple(row) == (None, None)
