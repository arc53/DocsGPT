"""Migration tests for 0038_connections: columns, backfill and round trip."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0037 = "0037_request_traces"


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"


def _run_alembic(url: str, *args: str) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _seed_legacy(conn) -> dict:
    """Rows as a pre-0038 install left them."""
    ids = {}
    ids["drive"] = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, session_token, user_email, status, token_info) "
            "VALUES ('alice', 'google_drive', 'tok-a', 'alice@example.com', 'authorized', "
            "CAST(:ti AS jsonb)) RETURNING id"
        ),
        {"ti": json.dumps({"access_token": "at", "refresh_token": "rt"})},
    ).scalar()
    ids["mcp"] = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, server_url, session_data) "
            "VALUES ('alice', 'mcp:https://mcp.example.com', 'https://mcp.example.com', CAST(:sd AS jsonb)) "
            "RETURNING id"
        ),
        {"sd": json.dumps({"tokens": {"access_token": "m"}})},
    ).scalar()
    ids["source"] = conn.execute(
        text(
            "INSERT INTO sources (user_id, name, type, remote_data) "
            "VALUES ('alice', 'Handbook', 'connector:file', CAST(:rd AS jsonb)) RETURNING id"
        ),
        {"rd": json.dumps({"provider": "google_drive", "file_ids": ["f1"]})},
    ).scalar()
    ids["other_source"] = conn.execute(
        text(
            "INSERT INTO sources (user_id, name, type, remote_data) "
            "VALUES ('bob', 'Bob files', 'connector:file', CAST(:rd AS jsonb)) RETURNING id"
        ),
        {"rd": json.dumps({"provider": "google_drive"})},
    ).scalar()
    ids["mcp_tool"] = conn.execute(
        text(
            "INSERT INTO user_tools (user_id, name, config) "
            "VALUES ('alice', 'mcp_tool', CAST(:c AS jsonb)) RETURNING id"
        ),
        {"c": json.dumps({"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth"})},
    ).scalar()
    ids["bearer_tool"] = conn.execute(
        text(
            "INSERT INTO user_tools (user_id, name, config) "
            "VALUES ('alice', 'mcp_tool', CAST(:c AS jsonb)) RETURNING id"
        ),
        {"c": json.dumps({"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer"})},
    ).scalar()
    return ids


class TestMigration0038:
    def test_head_has_connection_columns(self, pg_engine):
        with pg_engine.connect() as conn:
            assert {"connector_key", "display_name", "account_label", "auth_kind", "updated_at"} <= _columns(
                conn, "connector_sessions"
            )
            assert "connection_id" in _columns(conn, "sources")
            assert "connection_id" in _columns(conn, "user_tools")

    def test_backfill_links_legacy_rows(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0037)
        with pg_engine.begin() as conn:
            ids = _seed_legacy(conn)
        _run_alembic(url, "upgrade", "head")

        with pg_engine.connect() as conn:
            drive = conn.execute(
                text(
                    "SELECT connector_key, auth_kind, display_name, account_label "
                    "FROM connector_sessions WHERE id = :id"
                ),
                {"id": ids["drive"]},
            ).one()
            assert tuple(drive) == ("google_drive", "oauth", "Google Drive", "alice@example.com")

            mcp = conn.execute(
                text("SELECT connector_key, auth_kind, display_name FROM connector_sessions WHERE id = :id"),
                {"id": ids["mcp"]},
            ).one()
            assert tuple(mcp) == ("custom_mcp", "mcp_oauth", "mcp.example.com")

            linked = conn.execute(
                text("SELECT connection_id FROM sources WHERE id = :id"), {"id": ids["source"]}
            ).scalar()
            assert linked == ids["drive"]
            # Bob has no session for the provider: nothing to link.
            assert (
                conn.execute(
                    text("SELECT connection_id FROM sources WHERE id = :id"), {"id": ids["other_source"]}
                ).scalar()
                is None
            )
            tool = conn.execute(
                text("SELECT connection_id FROM user_tools WHERE id = :id"), {"id": ids["mcp_tool"]}
            ).scalar()
            assert tool == ids["mcp"]
            # A bearer MCP tool has no OAuth session to point at.
            bearer = conn.execute(
                text("SELECT connection_id FROM user_tools WHERE id = :id"), {"id": ids["bearer_tool"]}
            ).scalar()
            assert bearer is None

    def test_downgrade_then_upgrade_is_idempotent(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0037)
        with pg_engine.connect() as conn:
            assert "connector_key" not in _columns(conn, "connector_sessions")
            assert "connection_id" not in _columns(conn, "sources")
        _run_alembic(url, "upgrade", "head")
        _run_alembic(url, "downgrade", _0037)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert "connector_key" in _columns(conn, "connector_sessions")
            assert "connection_id" in _columns(conn, "user_tools")
