"""Migration round-trip test for 0011_schedules_nullable_agent."""

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


def _column_is_nullable(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None and row[0] == "YES"


def _alembic_version(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


_0011_REVISION = "0011_schedules_nullable_agent"
_0010_REVISION = "0010_schedules"


class TestMigration0011RoundTrip:
    def test_head_state_has_nullable_agent_id(self, pg_engine):
        # pg_engine upgrades to ``head`` which includes 0011.
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0011_REVISION
            assert _column_is_nullable(conn, "schedules", "agent_id")
            assert _column_is_nullable(conn, "schedule_runs", "agent_id")

    def test_agentless_insert_succeeds_at_head(self, pg_engine):
        # Sanity: NULL agent_id is accepted by the schema.
        with pg_engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO schedules
                        (user_id, agent_id, trigger_type, run_at, instruction)
                    VALUES (
                        'u-agentless', NULL, 'once',
                        now() + interval '1 hour', 'go'
                    )
                    RETURNING id
                    """
                ),
            ).fetchone()
            schedule_id = str(row[0])
            conn.execute(
                text(
                    """
                    INSERT INTO schedule_runs
                        (schedule_id, user_id, agent_id, scheduled_for)
                    VALUES (CAST(:s AS uuid), 'u-agentless', NULL, now())
                    """
                ),
                {"s": schedule_id},
            )
            cnt = conn.execute(
                text(
                    "SELECT count(*) FROM schedules "
                    "WHERE agent_id IS NULL AND user_id = 'u-agentless'"
                )
            ).scalar()
            assert cnt == 1

    def test_downgrade_restores_not_null_when_no_nulls(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        # Downgrade to 0010: agent_id NOT NULL is restored.
        _run_alembic(url, "downgrade", _0010_REVISION)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0010_REVISION
            assert not _column_is_nullable(conn, "schedules", "agent_id")
            assert not _column_is_nullable(conn, "schedule_runs", "agent_id")
        _run_alembic(url, "upgrade", "head")

    def test_downgrade_fails_when_agentless_rows_present(self, pg_engine):
        """Downgrade with NULL agent_id rows raises loudly (no data loss)."""
        # Start at head (already there). Insert an agentless row.
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO schedules
                        (user_id, agent_id, trigger_type, run_at, instruction)
                    VALUES (
                        'u-block', NULL, 'once',
                        now() + interval '1 hour', 'go'
                    )
                    """
                )
            )
        url = pg_engine.url.render_as_string(hide_password=False)
        with pytest.raises(subprocess.CalledProcessError):
            _run_alembic(url, "downgrade", _0010_REVISION)
        # Clean up so downstream tests aren't affected.
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM schedules WHERE user_id = 'u-block'")
            )

    def test_agentless_rows_survive_unrelated_agent_delete(self, pg_engine):
        """Agentless rows (agent_id IS NULL) aren't matched by FK CASCADE."""
        with pg_engine.begin() as conn:
            agent_id = conn.execute(
                text(
                    "INSERT INTO agents (user_id, name, status) "
                    "VALUES ('u1', 'a', 'draft') RETURNING id"
                )
            ).fetchone()[0]
            conn.execute(
                text(
                    "INSERT INTO schedules "
                    "(user_id, agent_id, trigger_type, run_at, instruction) "
                    "VALUES ('u-agentless', NULL, 'once', "
                    "now() + interval '1 hour', 'survive')"
                )
            )
            conn.execute(
                text("DELETE FROM agents WHERE id = CAST(:a AS uuid)"),
                {"a": str(agent_id)},
            )
            count = conn.execute(
                text(
                    "SELECT count(*) FROM schedules "
                    "WHERE user_id = 'u-agentless'"
                )
            ).scalar()
            assert count == 1

    def test_full_round_trip_lands_back_at_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0010_REVISION)
        _run_alembic(url, "upgrade", _0011_REVISION)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0011_REVISION
            assert _column_is_nullable(conn, "schedules", "agent_id")
            assert _column_is_nullable(conn, "schedule_runs", "agent_id")
        _run_alembic(url, "upgrade", "head")
