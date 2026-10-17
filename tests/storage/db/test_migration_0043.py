"""Migration round-trip test for 0043_wiki_outside_edits."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0042 = "0042_schedule_created_via_api"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _column_exists(conn) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'sources' AND column_name = 'wiki_outside_edits'"
        )
    ).fetchone() is not None


class TestMigration0043RoundTrip:
    def test_head_defaults_to_off(self, pg_engine):
        with pg_engine.begin() as conn:
            value = conn.execute(
                text("INSERT INTO sources (user_id, name) VALUES ('u', 'w') RETURNING wiki_outside_edits")
            ).scalar()
        assert value is False

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0042)
        with pg_engine.connect() as conn:
            assert not _column_exists(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _column_exists(conn)
