"""Migration round-trip test for 0053_workflow_run_progress."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0052 = "0052_connector_oauth_flows"
_EDITED = datetime(2030, 3, 4, 9, tzinfo=timezone.utc)


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _has_progress(conn) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'workflow_runs' AND column_name = 'progress'"
            )
        ).scalar()
    )


def _has_plan_changed_at(conn) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'schedules' AND column_name = 'plan_changed_at'"
            )
        ).scalar()
    )


class TestMigration0053:
    def test_round_trip(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.connect() as conn:
            assert _has_progress(conn)
        _run_alembic(url, "downgrade", _0052)
        with pg_engine.connect() as conn:
            assert not _has_progress(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _has_progress(conn)

    def test_plan_changed_at_is_backfilled_from_updated_at(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.connect() as conn:
            assert _has_plan_changed_at(conn)
        _run_alembic(url, "downgrade", _0052)
        with pg_engine.begin() as conn:
            assert not _has_plan_changed_at(conn)
            conn.execute(text("ALTER TABLE schedules DISABLE TRIGGER schedules_set_updated_at"))
            schedule_id = conn.execute(
                text(
                    "INSERT INTO schedules (user_id, trigger_type, instruction, cron, updated_at) "
                    "VALUES ('u-0053', 'recurring', 'x', '0 9 * * *', :t) RETURNING id"
                ),
                {"t": _EDITED},
            ).scalar()
            conn.execute(text("ALTER TABLE schedules ENABLE TRIGGER schedules_set_updated_at"))
        try:
            _run_alembic(url, "upgrade", "head")
            with pg_engine.connect() as conn:
                row = conn.execute(
                    text("SELECT updated_at, plan_changed_at FROM schedules WHERE id = :id"),
                    {"id": schedule_id},
                ).one()
            # The backfill copies updated_at and leaves it where it was.
            assert row.updated_at == _EDITED
            assert row.plan_changed_at == _EDITED
        finally:
            with pg_engine.begin() as conn:
                conn.execute(text("DELETE FROM schedules WHERE id = :id"), {"id": schedule_id})
