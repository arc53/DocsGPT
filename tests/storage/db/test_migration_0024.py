"""Migration round-trip test for 0024_wiki_pages_updated_via."""

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


_0024 = "0024_wiki_pages_updated_via"
_0023 = "0023_wiki_pages"


class TestMigration0024RoundTrip:
    def test_single_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        assert len(_alembic_heads(url)) == 1

    def test_head_has_updated_via_column(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0024
            assert _column_exists(conn, "wiki_pages", "updated_via")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0023)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0023
            assert not _column_exists(conn, "wiki_pages", "updated_via")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0024
            assert _column_exists(conn, "wiki_pages", "updated_via")
