"""The ``cannot_complete`` run error type survives an idempotent migration round trip."""

import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository


def _run(conn) -> str:
    now = datetime.now(timezone.utc)
    schedule = SchedulesRepository(conn).create(
        user_id="u", agent_id=None, trigger_type="recurring", instruction="check the site",
        cron="0 9 * * *", next_run_at=now + timedelta(hours=1),
    )
    return str(ScheduleRunsRepository(conn).record_pending(str(schedule["id"]), "u", None, now)["id"])


def _set_error_type(conn, run_id: str, value: str) -> None:
    conn.execute(
        text("UPDATE schedule_runs SET error_type = :v WHERE id = CAST(:id AS uuid)"), {"v": value, "id": run_id},
    )


def _error_type(conn, run_id: str) -> str:
    return conn.execute(
        text("SELECT error_type FROM schedule_runs WHERE id = CAST(:id AS uuid)"), {"id": run_id},
    ).scalar()


def test_round_trip_allows_then_folds_the_new_value(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0063_schedule_run_cannot_complete")
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        run_id = _run(pg_conn)
        _set_error_type(pg_conn, run_id, "cannot_complete")
        assert _error_type(pg_conn, run_id) == "cannot_complete"

        migration.downgrade()
        migration.downgrade()
        assert _error_type(pg_conn, run_id) == "agent_error"
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            _set_error_type(pg_conn, run_id, "cannot_complete")
        _set_error_type(pg_conn, run_id, "empty_output")

        migration.upgrade()
        _set_error_type(pg_conn, run_id, "cannot_complete")
        assert _error_type(pg_conn, run_id) == "cannot_complete"
