"""Migration round-trip test for 0047_background_jobs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0046 = "0046_pending_tool_state_json"
_TABLES = ("background_jobs", "conversation_wakes")


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _tables(conn) -> set:
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_name IN ('background_jobs', 'conversation_wakes')"
        )
    ).fetchall()
    return {r[0] for r in rows}


class TestMigration0047RoundTrip:
    def test_head_has_both_tables(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _tables(conn) == set(_TABLES)

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0046)
        with pg_engine.connect() as conn:
            assert _tables(conn) == set()
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _tables(conn) == set(_TABLES)

    def test_status_check_rejects_unknown_values(self, pg_engine):
        with pg_engine.connect() as conn:
            conn.execute(text("INSERT INTO users (user_id) VALUES ('u1') ON CONFLICT DO NOTHING"))
            with pytest.raises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO background_jobs (user_id, tool_name, action_name, status, deadline_at) "
                        "VALUES ('u1', 't', 'a', 'running', now())"
                    )
                )
