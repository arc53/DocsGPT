"""Migration round-trip test for 0046_pending_tool_state_json."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0045 = "0045_attachment_archive_idx"
_COLUMNS = ("messages", "pending_tool_calls", "tools_dict", "tool_schemas", "agent_config", "client_tools")
_PARAMS = '{"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}}'


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _types(conn) -> dict:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'pending_tool_state'"
        )
    ).fetchall()
    return {name: kind for name, kind in rows if name in _COLUMNS}


def _insert(conn) -> str:
    conv_id = conn.execute(
        text("INSERT INTO conversations (user_id, name) VALUES ('u', 'c') RETURNING id")
    ).scalar()
    conn.execute(
        text(
            "INSERT INTO pending_tool_state (conversation_id, user_id, messages, pending_tool_calls, "
            "tools_dict, tool_schemas, agent_config, client_tools, expires_at) "
            "VALUES (:c, 'u', '[]', '[]', '{}', CAST(:p AS text)::json, '{}', NULL, now() + interval '30 minutes')"
        ),
        {"c": conv_id, "p": f"[{_PARAMS}]"},
    )
    return str(conv_id)


class TestMigration0046RoundTrip:
    def test_head_stores_json_in_written_order(self, pg_engine):
        with pg_engine.begin() as conn:
            assert set(_types(conn).values()) == {"json"}
            conv_id = _insert(conn)
            stored = conn.execute(
                text("SELECT tool_schemas::text FROM pending_tool_state WHERE conversation_id = :c"),
                {"c": conv_id},
            ).scalar()
        assert stored == f"[{_PARAMS}]"

    def test_downgrade_restores_jsonb_then_upgrade_keeps_rows(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            _insert(conn)
        _run_alembic(url, "downgrade", _0045)
        with pg_engine.connect() as conn:
            assert set(_types(conn).values()) == {"jsonb"}
            assert conn.execute(text("SELECT count(*) FROM pending_tool_state")).scalar() == 1
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert set(_types(conn).values()) == {"json"}
            assert conn.execute(text("SELECT count(*) FROM pending_tool_state")).scalar() == 1

    def test_upgrade_is_idempotent(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "stamp", _0045)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert set(_types(conn).values()) == {"json"}
