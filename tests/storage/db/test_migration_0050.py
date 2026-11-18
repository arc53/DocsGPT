"""Migration round-trip test for 0050_agent_type_default."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0049 = "0049_push_and_unread"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _column(conn) -> tuple[str, str | None]:
    row = conn.execute(
        text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'agents' AND column_name = 'agent_type'"
        )
    ).one()
    return row.is_nullable, row.column_default


def _insert(conn, name: str, agent_type: str | None) -> None:
    conn.execute(
        text("INSERT INTO agents (user_id, name, status, agent_type) VALUES ('u', :n, 'published', :t)"),
        {"n": name, "t": agent_type},
    )


class TestMigration0050:
    def test_head_defaults_to_classic_and_forbids_null(self, pg_engine):
        with pg_engine.begin() as conn:
            is_nullable, default = _column(conn)
            assert is_nullable == "NO"
            assert "classic" in default
            conn.execute(text("INSERT INTO agents (user_id, name, status) VALUES ('u', 'a', 'draft')"))
            assert conn.execute(text("SELECT agent_type FROM agents")).scalar() == "classic"

    def test_upgrade_repairs_null_and_blank_types(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0049)
        with pg_engine.begin() as conn:
            assert _column(conn) == ("YES", None)
            _insert(conn, "null(shared)", None)
            _insert(conn, "blank", "")
            _insert(conn, "spaces", "  ")
            _insert(conn, "agentic", "agentic")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            rows = dict(conn.execute(text("SELECT name, agent_type FROM agents")).fetchall())
        assert rows == {
            "null(shared)": "classic",
            "blank": "classic",
            "spaces": "classic",
            "agentic": "agentic",
        }
