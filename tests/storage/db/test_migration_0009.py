"""Migration round-trip test for 0009_tool_preferences."""

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
    """Run ``alembic`` against ``url``."""
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), *args],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _fk_exists(conn) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'memories'
                  AND constraint_name = 'memories_tool_id_fkey'
                  AND constraint_type = 'FOREIGN KEY'
                """
            )
        ).fetchone()
    )


def _trigger_exists(conn) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM pg_trigger "
                "WHERE tgname = 'user_tools_cleanup_memories'"
            )
        ).fetchone()
    )


def _function_exists(conn) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM pg_proc WHERE proname = 'cleanup_tool_memories'"
            )
        ).fetchone()
    )


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).fetchone()
    )


def _alembic_version(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


_0009_REVISION = "0009_tool_preferences"


class TestMigration0009RoundTrip:
    def test_head_state_has_trigger_no_fk(self, pg_engine):
        # The pg_engine fixture upgrades to ``head``; downgrade once to
        # land back at the 0009 revision this test characterises.
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0009_REVISION)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0009_REVISION
            assert not _fk_exists(conn)
            assert _trigger_exists(conn)
            assert _function_exists(conn)
            assert _column_exists(conn, "users", "tool_preferences")
        _run_alembic(url, "upgrade", "head")

    def test_downgrade_restores_fk_and_drops_trigger(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        # Drop down to 0009 first so the next downgrade hits 0009 → 0008.
        _run_alembic(url, "downgrade", _0009_REVISION)
        _run_alembic(url, "downgrade", "-1")
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == "0008_ingest_progress_status"
            assert _fk_exists(conn)
            assert not _trigger_exists(conn)
            assert not _function_exists(conn)
            assert not _column_exists(conn, "users", "tool_preferences")
        _run_alembic(url, "upgrade", "head")

    def test_full_round_trip_lands_back_at_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", "0008_ingest_progress_status")
        _run_alembic(url, "upgrade", _0009_REVISION)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0009_REVISION
            assert not _fk_exists(conn)
            assert _trigger_exists(conn)
            assert _function_exists(conn)
            assert _column_exists(conn, "users", "tool_preferences")
        _run_alembic(url, "upgrade", "head")

    def test_downgrade_purges_synthetic_id_memory_rows(self, pg_engine):
        """Downgrade DELETEs synthetic-id memory rows so the FK can be restored."""
        from application.agents.default_tools import default_tool_id

        url = pg_engine.url.render_as_string(hide_password=False)
        # Land on 0009 so synthetic-id rows are insertable (no FK yet).
        _run_alembic(url, "downgrade", _0009_REVISION)
        synthetic_id = default_tool_id("memory")
        with pg_engine.begin() as conn:
            real_tool_id = str(
                conn.execute(
                    text(
                        "INSERT INTO user_tools (user_id, name) "
                        "VALUES ('u-mig', 'memory') RETURNING id"
                    )
                ).scalar()
            )
            conn.execute(
                text(
                    "INSERT INTO memories (user_id, tool_id, path, content) "
                    "VALUES ('u-mig', CAST(:tid AS uuid), '/real', 'keep')"
                ),
                {"tid": real_tool_id},
            )
            conn.execute(
                text(
                    "INSERT INTO memories (user_id, tool_id, path, content) "
                    "VALUES ('u-mig', CAST(:tid AS uuid), '/synthetic', 'lose')"
                ),
                {"tid": synthetic_id},
            )

        _run_alembic(url, "downgrade", "-1")

        with pg_engine.connect() as conn:
            assert _fk_exists(conn)
            surviving = conn.execute(
                text("SELECT path FROM memories WHERE user_id = 'u-mig'")
            ).fetchall()
            paths = {row[0] for row in surviving}
            assert paths == {"/real"}

        # Restore so the engine teardown isn't left mid-migration.
        _run_alembic(url, "upgrade", "head")

    def test_upgrade_is_idempotent(self, pg_engine):
        """Re-running upgrade after physically downgrading succeeds."""
        url = pg_engine.url.render_as_string(hide_password=False)
        # Physically downgrade so the next upgrade actually re-runs the
        # 0009 DDL (a bare ``stamp`` would leave objects from later
        # revisions in place and the re-upgrade would collide on them).
        _run_alembic(url, "downgrade", "0008_ingest_progress_status")
        _run_alembic(url, "upgrade", _0009_REVISION)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0009_REVISION
            assert _trigger_exists(conn)
            assert _function_exists(conn)
        # Restore full head for teardown.
        _run_alembic(url, "upgrade", "head")
