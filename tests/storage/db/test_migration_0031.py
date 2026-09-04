"""Migration round-trip test for 0031_token_usage_cache_tokens."""

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


def _alembic_heads(url: str) -> list[str]:
    out = subprocess.check_output(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), "heads"],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


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


_0031 = "0031_token_usage_cache_tokens"
_0030 = "0030_superseded_messages"


class TestMigration0031RoundTrip:
    def test_single_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        assert len(_alembic_heads(url)) == 1

    def test_head_has_cache_columns(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0031
            assert _column_exists(conn, "token_usage", "cached_tokens")
            assert _column_exists(conn, "token_usage", "cache_write_tokens")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0030)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0030
            assert not _column_exists(conn, "token_usage", "cached_tokens")
            assert not _column_exists(conn, "token_usage", "cache_write_tokens")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0031
            assert _column_exists(conn, "token_usage", "cached_tokens")

    def test_existing_rows_read_null_cache_bins(self, pg_engine):
        """Rows written before 0031 must read NULL (unknown), not 0."""
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0030)
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO token_usage (user_id, prompt_tokens, generated_tokens) "
                    "VALUES ('u-mig31', 10, 1)"
                )
            )
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT cached_tokens, cache_write_tokens FROM token_usage "
                    "WHERE user_id = 'u-mig31'"
                )
            ).fetchone()
            assert tuple(row) == (None, None)
