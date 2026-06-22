"""Migration round-trip test for 0023_wiki_pages."""

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


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t AND table_schema = 'public'"
        ),
        {"t": table},
    ).fetchone()
    return row is not None


_0023 = "0023_wiki_pages"
_0022 = "0022_source_config"


class TestMigration0023RoundTrip:
    def test_single_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        assert len(_alembic_heads(url)) == 1

    def test_head_has_wiki_pages_table(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0023
            assert _table_exists(conn, "wiki_pages")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0022)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0022
            assert not _table_exists(conn, "wiki_pages")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0023
            assert _table_exists(conn, "wiki_pages")
