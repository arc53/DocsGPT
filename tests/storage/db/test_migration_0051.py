"""Migration round-trip test for 0051_device_jobs_links."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


pytestmark = pytest.mark.integration

_0050 = "0050_agent_type_default"


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


class TestMigration0051RoundTrip:
    def test_head_takes_a_device_job(self, pg_engine):
        with pg_engine.begin() as conn:
            assert conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = 'devices' "
                    "AND column_name = 'capabilities'"
                )
            ).fetchone() is not None
            job_id = _device_job(conn, _conversation(conn))
            assert conn.execute(
                text("SELECT runner FROM background_jobs WHERE id = CAST(:id AS uuid)"), {"id": job_id}
            ).scalar() == "device"

    def test_downgrade_reports_running_device_jobs_lost(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            job_id = _device_job(conn, _conversation(conn))
        _run_alembic(url, "downgrade", _0050)
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT status, runner, error FROM background_jobs WHERE id = CAST(:id AS uuid)"), {"id": job_id}
            ).one()
            assert row.status == "lost"
            assert row.runner == "inprocess"
            assert "verify before retrying" in row.error["message"]
            conversation_id = _conversation(conn)
            # Only the restored runner check refuses it, not some unrelated error.
            with pytest.raises(IntegrityError, match="background_jobs_runner_chk"):
                _device_job(conn, conversation_id)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.begin() as conn:
            _device_job(conn, _conversation(conn))


    def test_downgrade_revokes_links_signed_a_new_way(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            conversation_id = _conversation(conn)
            schedule_id = conn.execute(
                text(
                    "INSERT INTO schedules (user_id, trigger_type, instruction, status) "
                    "VALUES ('u1', 'monitor', 'x', 'active') RETURNING id"
                )
            ).scalar()
            for index, scheme in enumerate(("stripe", "github")):
                conn.execute(
                    text(
                        "INSERT INTO trigger_links (monitor_id, user_id, conversation_id, token_hash, kind, "
                        "signature_scheme, expires_at, allow_get, signature_header) VALUES (:m, 'u1', "
                        "CAST(:c AS uuid), :h, 'webhook', :s, now() + interval '1 day', true, 'X-T')"
                    ),
                    {"m": schedule_id, "c": conversation_id, "h": f"h{index}", "s": scheme},
                )
        _run_alembic(url, "downgrade", _0050)
        with pg_engine.connect() as conn:
            rows = {
                row.token_hash: row
                for row in conn.execute(text("SELECT token_hash, signature_scheme, revoked_at FROM trigger_links"))
            }
        assert rows["h0"].revoked_at is not None and rows["h0"].signature_scheme == "hmac_sha256"
        assert rows["h1"].revoked_at is None and rows["h1"].signature_scheme == "github"
        _run_alembic(url, "upgrade", "head")
