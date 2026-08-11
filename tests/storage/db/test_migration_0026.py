"""Migration round-trip + backfill test for 0026_stack_logs_agent_id."""

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


def _index_exists(conn, name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
        {"n": name},
    ).fetchone()
    return row is not None


_0026 = "0026_stack_logs_agent_id"
_0025 = "0025_artifacts"


class TestMigration0026RoundTrip:
    def test_single_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        assert len(_alembic_heads(url)) == 1

    def test_head_has_agent_id_column_and_index(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0026
            assert _column_exists(conn, "stack_logs", "agent_id")
            assert _index_exists(conn, "ix_stack_logs_agent_id")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0025)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0025
            assert not _column_exists(conn, "stack_logs", "agent_id")
            assert not _index_exists(conn, "ix_stack_logs_agent_id")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0026
            assert _column_exists(conn, "stack_logs", "agent_id")

    def test_upgrade_backfills_agent_id_from_api_key(self, pg_engine):
        """A legacy stack_logs row (written before the column existed) is
        attributed to its agent by matching the stored api_key to
        ``agents.key`` during the upgrade."""
        from application.storage.db.repositories.agents import AgentsRepository

        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0025)

        with pg_engine.begin() as conn:
            agent = AgentsRepository(conn).create(
                "u-mig26", "a", "published", key="mig26-key",
            )
            agent_id = str(agent["id"])
            # Pre-0026 shape: no agent_id column.
            conn.execute(
                text(
                    "INSERT INTO stack_logs "
                    "(activity_id, endpoint, level, api_key, stacks) "
                    "VALUES ('mig26-act', 'webhook', 'info', 'mig26-key', "
                    "'[]'::jsonb)"
                )
            )
            # A row whose key matches no agent must stay NULL.
            conn.execute(
                text(
                    "INSERT INTO stack_logs "
                    "(activity_id, endpoint, level, api_key, stacks) "
                    "VALUES ('mig26-orphan', 'webhook', 'info', 'no-such-key', "
                    "'[]'::jsonb)"
                )
            )

        _run_alembic(url, "upgrade", "head")

        with pg_engine.connect() as conn:
            matched = conn.execute(
                text(
                    "SELECT agent_id FROM stack_logs "
                    "WHERE activity_id = 'mig26-act'"
                )
            ).fetchone()
            orphan = conn.execute(
                text(
                    "SELECT agent_id FROM stack_logs "
                    "WHERE activity_id = 'mig26-orphan'"
                )
            ).fetchone()
        assert str(matched._mapping["agent_id"]) == agent_id
        assert orphan._mapping["agent_id"] is None
