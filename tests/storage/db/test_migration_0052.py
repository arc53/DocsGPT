"""Migration round-trip test for 0052_connector_oauth_flows."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


pytestmark = pytest.mark.integration

_0051 = "0051_device_jobs_links"


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _connection(conn) -> str:
    return str(
        conn.execute(
            text("INSERT INTO connector_sessions (user_id, provider, status) VALUES ('u1', 'google_drive', 'pending') "
                 "RETURNING id")
        ).scalar()
    )


def _flow(conn, connection_id: str, state_hash: str) -> None:
    conn.execute(
        text(
            "INSERT INTO connector_oauth_flows (user_id, provider, connection_id, state_hash, return_origin, "
            "expires_at) VALUES ('u1', 'google_drive', CAST(:c AS uuid), :h, 'https://app.example.com', "
            "now() + interval '15 minutes')"
        ),
        {"c": connection_id, "h": state_hash},
    )


def _has_table(conn) -> bool:
    return conn.execute(text("SELECT to_regclass('public.connector_oauth_flows')")).scalar() is not None


class TestMigration0052RoundTrip:
    def test_head_keeps_state_unique_and_follows_its_connection(self, pg_engine):
        with pg_engine.begin() as conn:
            connection_id = _connection(conn)
            _flow(conn, connection_id, "h1")
        with pytest.raises(IntegrityError, match="connector_oauth_flows_state_hash_key"):
            with pg_engine.begin() as conn:
                _flow(conn, connection_id, "h1")
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM connector_sessions WHERE id = CAST(:c AS uuid)"), {"c": connection_id})
            assert conn.execute(text("SELECT count(*) FROM connector_oauth_flows")).scalar() == 0

    def test_downgrade_drops_the_table(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            _flow(conn, _connection(conn), "h2")
        _run_alembic(url, "downgrade", _0051)
        with pg_engine.connect() as conn:
            assert not _has_table(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _has_table(conn)
