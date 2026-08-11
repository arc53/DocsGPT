"""Sanity checks for the 0010 scheduler migration."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _insert_agent(conn, user_id: str = "u1") -> str:
    row = conn.execute(
        text(
            "INSERT INTO agents (user_id, name, status) "
            "VALUES (:u, 'a', 'draft') RETURNING id"
        ),
        {"u": user_id},
    ).fetchone()
    return str(row[0])


class TestSchedulesSchema:
    def test_tables_exist(self, pg_conn):
        for table in ("schedules", "schedule_runs"):
            res = pg_conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = :t"
                ),
                {"t": table},
            ).fetchone()
            assert res is not None, f"table {table} missing"

    def test_trigger_type_check(self, pg_conn):
        agent_id = _insert_agent(pg_conn)
        with pytest.raises(IntegrityError):
            pg_conn.execute(
                text(
                    "INSERT INTO schedules (user_id, agent_id, trigger_type, instruction) "
                    "VALUES ('u', CAST(:a AS uuid), 'bad', 'go')"
                ),
                {"a": agent_id},
            )

    def test_recurring_requires_cron(self, pg_conn):
        agent_id = _insert_agent(pg_conn)
        with pytest.raises(IntegrityError):
            pg_conn.execute(
                text(
                    "INSERT INTO schedules (user_id, agent_id, trigger_type, instruction) "
                    "VALUES ('u', CAST(:a AS uuid), 'recurring', 'go')"
                ),
                {"a": agent_id},
            )

    def test_once_requires_run_at(self, pg_conn):
        agent_id = _insert_agent(pg_conn)
        with pytest.raises(IntegrityError):
            pg_conn.execute(
                text(
                    "INSERT INTO schedules (user_id, agent_id, trigger_type, instruction) "
                    "VALUES ('u', CAST(:a AS uuid), 'once', 'go')"
                ),
                {"a": agent_id},
            )


class TestAgentCascade:
    def test_deleting_agent_cascades_through_schedule_runs(self, pg_conn):
        """Both schedules.agent_id and schedule_runs.agent_id cascade-delete
        on agents(id); pin the direct schedule_runs branch (redundant by
        design with the schedules->schedule_runs cascade)."""
        agent_id = _insert_agent(pg_conn)
        schedule_id = pg_conn.execute(
            text(
                """
                INSERT INTO schedules
                    (user_id, agent_id, trigger_type, run_at, instruction)
                VALUES (
                    'u', CAST(:a AS uuid), 'once',
                    now() + interval '1 hour', 'go'
                )
                RETURNING id
                """
            ),
            {"a": agent_id},
        ).fetchone()[0]
        pg_conn.execute(
            text(
                """
                INSERT INTO schedule_runs
                    (schedule_id, user_id, agent_id, scheduled_for)
                VALUES (CAST(:s AS uuid), 'u', CAST(:a AS uuid), now())
                """
            ),
            {"s": str(schedule_id), "a": agent_id},
        )

        pg_conn.execute(
            text("DELETE FROM agents WHERE id = CAST(:a AS uuid)"),
            {"a": agent_id},
        )

        remaining_schedules = pg_conn.execute(
            text(
                "SELECT count(*) FROM schedules "
                "WHERE agent_id = CAST(:a AS uuid)"
            ),
            {"a": agent_id},
        ).scalar()
        remaining_runs = pg_conn.execute(
            text(
                "SELECT count(*) FROM schedule_runs "
                "WHERE agent_id = CAST(:a AS uuid)"
            ),
            {"a": agent_id},
        ).scalar()
        assert remaining_schedules == 0
        assert remaining_runs == 0


class TestScheduleRunsDedup:
    def test_unique_schedule_id_scheduled_for(self, pg_conn):
        agent_id = _insert_agent(pg_conn)
        schedule_id = pg_conn.execute(
            text(
                """
                INSERT INTO schedules
                    (user_id, agent_id, trigger_type, run_at, instruction)
                VALUES (
                    'u', CAST(:a AS uuid), 'once',
                    now() + interval '1 hour', 'go'
                )
                RETURNING id
                """
            ),
            {"a": agent_id},
        ).fetchone()[0]

        pg_conn.execute(
            text(
                """
                INSERT INTO schedule_runs
                    (schedule_id, user_id, agent_id, scheduled_for)
                VALUES (CAST(:s AS uuid), 'u', CAST(:a AS uuid), now())
                """
            ),
            {"s": str(schedule_id), "a": agent_id},
        )

        with pytest.raises(IntegrityError):
            pg_conn.execute(
                text(
                    """
                    WITH first AS (
                        SELECT scheduled_for
                        FROM schedule_runs
                        WHERE schedule_id = CAST(:s AS uuid)
                    )
                    INSERT INTO schedule_runs
                        (schedule_id, user_id, agent_id, scheduled_for)
                    SELECT CAST(:s AS uuid), 'u', CAST(:a AS uuid), scheduled_for
                    FROM first
                    """
                ),
                {"s": str(schedule_id), "a": agent_id},
            )
