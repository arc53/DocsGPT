"""Migration round-trip test for 0037_request_traces."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"


def _run_alembic(url: str, *args: str) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), *args],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _alembic_version(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _table_exists(conn, table: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar() is not None


_0037 = "0037_request_traces"
_0036 = "0036_device_audit_created_idx"


class TestMigration0037RoundTrip:
    def test_head_has_request_traces(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) >= _0037
            assert _table_exists(conn, "request_traces")

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0036)
        with pg_engine.connect() as conn:
            assert _alembic_version(conn) == _0036
            assert not _table_exists(conn, "request_traces")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _table_exists(conn, "request_traces")

    def test_status_check_rejects_unknown_status(self, pg_engine):
        with pytest.raises(Exception):
            with pg_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO request_traces (id, source, status, started_at) "
                        "VALUES (gen_random_uuid(), 'stream', 'weird', now())"
                    )
                )

    def test_listing_and_deletion_indexes_exist(self, pg_engine):
        with pg_engine.connect() as conn:
            names = set(
                conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'request_traces'")
                ).scalars()
            )
        assert {
            "request_traces_conversation_idx",
            "request_traces_user_source_started_idx",
            "request_traces_agent_source_started_idx",
        } <= names
