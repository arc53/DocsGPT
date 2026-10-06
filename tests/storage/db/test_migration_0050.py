"""Migration round-trip test for 0050_device_jobs_links."""

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


def _conversation(conn) -> str:
    return str(
        conn.execute(text("INSERT INTO conversations (user_id, name) VALUES ('u1', 'c') RETURNING id")).scalar()
    )


def _device_job(conn, conversation_id: str) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO background_jobs (user_id, conversation_id, tool_name, action_name, runner, deadline_at) "
                "VALUES ('u1', CAST(:c AS uuid), 'remote_device', 'run_command', 'device', now() + interval '1 hour') "
                "RETURNING id"
            ),
            {"c": conversation_id},
        ).scalar()
    )


class TestMigration0050RoundTrip:
    def test_head_takes_a_device_job(self, pg_engine):
        with pg_engine.begin() as conn:
            job_id = _device_job(conn, _conversation(conn))
            assert conn.execute(
                text("SELECT runner FROM background_jobs WHERE id = CAST(:id AS uuid)"), {"id": job_id}
            ).scalar() == "device"

    def test_downgrade_reports_running_device_jobs_lost(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            job_id = _device_job(conn, _conversation(conn))
        _run_alembic(url, "downgrade", _0049)
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT status, runner, error FROM background_jobs WHERE id = CAST(:id AS uuid)"), {"id": job_id}
            ).one()
            assert row.status == "lost"
            assert row.runner == "inprocess"
            assert "verify before retrying" in row.error["message"]
            with pytest.raises(Exception):
                _device_job(conn, _conversation(conn))
        _run_alembic(url, "upgrade", "head")
        with pg_engine.begin() as conn:
            _device_job(conn, _conversation(conn))
