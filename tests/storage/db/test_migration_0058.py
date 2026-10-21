"""Migration round-trip test for 0058_conversation_label_sources."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_PREVIOUS = "0057_conversation_labels"
_COLUMNS = {"source_updated_at": "timestamp with time zone", "source_hash": "text"}


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _columns(conn) -> dict[str, str]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'conversation_labels' "
            "AND column_name = ANY(CAST(:names AS text[]))"
        ),
        {"names": list(_COLUMNS)},
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _labelled(conn) -> str:
    cid = conn.execute(text("INSERT INTO conversations (user_id) VALUES ('u') RETURNING CAST(id AS text)")).scalar()
    conn.execute(
        text(
            "INSERT INTO conversation_labels (conversation_id, user_id, level, label, probabilities, schema_hash, "
            "model_version, occurred_at) VALUES (CAST(:cid AS uuid), 'u', 'conversation', 'goal_met', "
            "'{}'::jsonb, 'h', 'v', now())"
        ),
        {"cid": cid},
    )
    return cid


def _count(conn, cid: str) -> int:
    return conn.execute(
        text("SELECT COUNT(*) FROM conversation_labels WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid}
    ).scalar()


class TestMigration0058RoundTrip:
    def test_head_adds_the_source_columns_empty_on_existing_rows(self, pg_engine):
        with pg_engine.begin() as conn:
            assert _columns(conn) == _COLUMNS
            cid = _labelled(conn)
            row = conn.execute(
                text("SELECT source_updated_at, source_hash FROM conversation_labels "
                     "WHERE conversation_id = CAST(:cid AS uuid)"),
                {"cid": cid},
            ).one()
            assert tuple(row) == (None, None)

    def test_downgrade_drops_the_columns_and_keeps_the_rows(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            cid = _labelled(conn)
        _run_alembic(url, "downgrade", _PREVIOUS)
        with pg_engine.connect() as conn:
            assert _columns(conn) == {}
            assert _count(conn, cid) == 1
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _columns(conn) == _COLUMNS
            assert _count(conn, cid) == 1
