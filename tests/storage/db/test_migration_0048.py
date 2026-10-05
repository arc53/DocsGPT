"""Migration round-trip test for 0048_monitors_and_trigger_links."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0047 = "0047_background_jobs"
_TABLES = ("monitors", "trigger_links", "trigger_hits")


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
            "AND table_name IN ('monitors', 'trigger_links', 'trigger_hits')"
        )
    ).fetchall()
    return {r[0] for r in rows}


def _monitor_schedule(conn) -> None:
    conn.execute(text("INSERT INTO users (user_id) VALUES ('u1') ON CONFLICT DO NOTHING"))
    conn.execute(
        text(
            "INSERT INTO schedules (user_id, trigger_type, instruction, next_run_at) "
            "VALUES ('u1', 'monitor', 'tell me', now())"
        )
    )


class TestMigration0048RoundTrip:
    def test_head_has_the_tables_and_takes_monitor_schedules(self, pg_engine):
        with pg_engine.begin() as conn:
            assert _tables(conn) == set(_TABLES)
            _monitor_schedule(conn)

    def test_downgrade_drops_monitors_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            _monitor_schedule(conn)
        _run_alembic(url, "downgrade", _0047)
        with pg_engine.begin() as conn:
            assert _tables(conn) == set()
            assert conn.execute(text("SELECT COUNT(*) FROM schedules WHERE trigger_type = 'monitor'")).scalar() == 0
            with pytest.raises(Exception):
                _monitor_schedule(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.begin() as conn:
            assert _tables(conn) == set(_TABLES)
            _monitor_schedule(conn)

    def test_link_kind_and_scheme_checks(self, pg_engine):
        with pg_engine.connect() as conn:
            conn.execute(text("INSERT INTO users (user_id) VALUES ('u1') ON CONFLICT DO NOTHING"))
            with pytest.raises(Exception):
                conn.execute(
                    text(
                        "INSERT INTO trigger_links (monitor_id, user_id, conversation_id, token_hash, kind, "
                        "expires_at) VALUES (gen_random_uuid(), 'u1', gen_random_uuid(), 'h', 'email', now())"
                    )
                )
