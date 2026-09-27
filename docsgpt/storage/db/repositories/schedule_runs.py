"""Repository for ``schedule_runs`` (record_pending is the dedup primitive)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import row_to_dict


_ALLOWED_UPDATES = frozenset(
    {
        "status", "started_at", "finished_at", "output", "output_truncated",
        "error", "error_type", "prompt_tokens", "generated_tokens",
        "conversation_id", "message_id", "celery_task_id",
    }
)


class ScheduleRunsRepository:
    """CRUD + dedup insert + reconciliation sweep for ``schedule_runs``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record_pending(
        self,
        schedule_id: str,
        user_id: str,
        agent_id: Optional[str],
        scheduled_for: datetime,
        *,
        trigger_source: str = "cron",
    ) -> Optional[dict]:
        """Insert a ``pending`` row; ``None`` on conflict (already claimed)."""
        row = self._conn.execute(
            text(
                """
                INSERT INTO schedule_runs (
                    schedule_id, user_id, agent_id, scheduled_for,
                    trigger_source, status
                ) VALUES (
                    CAST(:schedule_id AS uuid),
                    :user_id,
                    CAST(:agent_id AS uuid),
                    :scheduled_for,
                    :trigger_source,
                    'pending'
                )
                ON CONFLICT (schedule_id, scheduled_for) DO NOTHING
                RETURNING *
                """
            ),
            {
                "schedule_id": str(schedule_id),
                "user_id": user_id,
                "agent_id": str(agent_id) if agent_id else None,
                "scheduled_for": scheduled_for,
                "trigger_source": trigger_source,
            },
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def record_skipped(
        self,
        schedule_id: str,
        user_id: str,
        agent_id: Optional[str],
        scheduled_for: datetime,
        *,
        error_type: str,
        error: Optional[str] = None,
    ) -> Optional[dict]:
        """Write a terminal ``skipped`` row; returns ``None`` on conflict."""
        row = self._conn.execute(
            text(
                """
                INSERT INTO schedule_runs (
                    schedule_id, user_id, agent_id, scheduled_for,
                    trigger_source, status, started_at, finished_at,
                    error, error_type
                ) VALUES (
                    CAST(:schedule_id AS uuid),
                    :user_id,
                    CAST(:agent_id AS uuid),
                    :scheduled_for,
                    'cron',
                    'skipped',
                    now(),
                    now(),
                    :error,
                    :error_type
                )
                ON CONFLICT (schedule_id, scheduled_for) DO NOTHING
                RETURNING *
                """
            ),
            {
                "schedule_id": str(schedule_id),
                "user_id": user_id,
                "agent_id": str(agent_id) if agent_id else None,
                "scheduled_for": scheduled_for,
                "error": error,
                "error_type": error_type,
            },
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, run_id: str, user_id: str) -> Optional[dict]:
        """Fetch an owned run row."""
        row = self._conn.execute(
            text(
                "SELECT * FROM schedule_runs "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": str(run_id), "user_id": user_id},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get_internal(self, run_id: str) -> Optional[dict]:
        """Fetch a run row with no ownership scoping (worker-only)."""
        row = self._conn.execute(
            text("SELECT * FROM schedule_runs WHERE id = CAST(:id AS uuid)"),
            {"id": str(run_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def has_active_run(self, schedule_id: str) -> bool:
        """True iff a ``pending``/``running`` run exists for the schedule."""
        scalar = self._conn.execute(
            text(
                "SELECT 1 FROM schedule_runs "
                "WHERE schedule_id = CAST(:id AS uuid) "
                "AND status IN ('pending', 'running') "
                "LIMIT 1"
            ),
            {"id": str(schedule_id)},
        ).first()
        return scalar is not None

    def list_runs(
        self,
        schedule_id: str,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Paginated newest-first run log for an owned schedule."""
        rows = self._conn.execute(
            text(
                """
                SELECT * FROM schedule_runs
                WHERE schedule_id = CAST(:id AS uuid) AND user_id = :user_id
                ORDER BY scheduled_for DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {
                "id": str(schedule_id),
                "user_id": user_id,
                "limit": int(limit),
                "offset": int(offset),
            },
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def stats_for_agent(
        self, agent_id: str, user_id: str, *, days: int = 30,
    ) -> dict:
        """Aggregate run stats for an agent's owned schedules over a window.

        Only runs of schedules owned by ``user_id`` on ``agent_id`` whose
        ``scheduled_for`` falls within the last ``days`` days are counted.

        Args:
            agent_id: Agent UUID the schedules belong to.
            user_id: Owner of the schedules (and runs).
            days: Window length in days, counted back from now.

        Returns:
            Dict with ``runs``, ``failed`` (``failed``/``timeout``),
            ``tokens`` (prompt + generated) and ``latest_failure`` — the
            most recent failed run's ``scheduled_for``/``status``/
            ``error_type``, or ``None`` when there is none.
        """
        row = self._conn.execute(
            text(
                """
                WITH window_runs AS (
                    SELECT r.scheduled_for, r.status, r.error_type,
                           r.prompt_tokens, r.generated_tokens
                    FROM schedule_runs r
                    JOIN schedules s ON s.id = r.schedule_id
                    WHERE s.agent_id = CAST(:agent_id AS uuid)
                      AND s.user_id = :user_id
                      AND r.user_id = :user_id
                      AND r.scheduled_for >= now() - make_interval(days => :days)
                ),
                latest_failure AS (
                    SELECT scheduled_for, status, error_type
                    FROM window_runs
                    WHERE status IN ('failed', 'timeout')
                    ORDER BY scheduled_for DESC
                    LIMIT 1
                )
                SELECT agg.runs, agg.failed, agg.tokens,
                       lf.scheduled_for AS latest_failure_scheduled_for,
                       lf.status AS latest_failure_status,
                       lf.error_type AS latest_failure_error_type
                FROM (
                    SELECT count(*) AS runs,
                           count(*) FILTER (
                               WHERE status IN ('failed', 'timeout')
                           ) AS failed,
                           COALESCE(
                               SUM(prompt_tokens + generated_tokens), 0
                           ) AS tokens
                    FROM window_runs
                ) agg
                LEFT JOIN latest_failure lf ON true
                """
            ),
            {"agent_id": str(agent_id), "user_id": user_id, "days": int(days)},
        ).fetchone()
        data = row_to_dict(row)
        latest_failure = None
        if data.get("latest_failure_scheduled_for") is not None:
            latest_failure = {
                "scheduled_for": data["latest_failure_scheduled_for"],
                "status": data["latest_failure_status"],
                "error_type": data["latest_failure_error_type"],
            }
        return {
            "runs": int(data.get("runs") or 0),
            "failed": int(data.get("failed") or 0),
            "tokens": int(data.get("tokens") or 0),
            "latest_failure": latest_failure,
        }

    def update(self, run_id: str, fields: dict) -> Optional[dict]:
        """Apply a whitelisted partial update to a run row."""
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATES}
        if not filtered:
            return self.get_internal(run_id)
        set_parts: list[str] = []
        params: dict[str, Any] = {"id": str(run_id)}
        for key, val in filtered.items():
            if key in ("conversation_id", "message_id"):
                set_parts.append(f"{key} = CAST(:{key} AS uuid)")
                params[key] = str(val) if val else None
            else:
                set_parts.append(f"{key} = :{key}")
                params[key] = val
        sql = (
            "UPDATE schedule_runs SET " + ", ".join(set_parts) +
            " WHERE id = CAST(:id AS uuid) RETURNING *"
        )
        row = self._conn.execute(text(sql), params).fetchone()
        return row_to_dict(row) if row is not None else None

    def mark_running(self, run_id: str, celery_task_id: Optional[str]) -> bool:
        """Flip ``pending`` → ``running`` and stamp ``started_at``."""
        result = self._conn.execute(
            text(
                """
                UPDATE schedule_runs
                SET status = 'running',
                    started_at = now(),
                    celery_task_id = :celery_task_id
                WHERE id = CAST(:id AS uuid)
                  AND status = 'pending'
                """
            ),
            {"id": str(run_id), "celery_task_id": celery_task_id},
        )
        return (result.rowcount or 0) > 0

    def list_stuck_running(
        self, *, age_minutes: int = 15, limit: int = 50,
    ) -> list[dict]:
        """Lock ``running`` rows past the soft-time-limit envelope."""
        rows = self._conn.execute(
            text(
                """
                SELECT * FROM schedule_runs
                WHERE status = 'running'
                  AND started_at IS NOT NULL
                  AND started_at < now() - make_interval(mins => :age)
                ORDER BY started_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"age": int(age_minutes), "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_stuck_pending(
        self, *, age_minutes: int = 15, limit: int = 50,
    ) -> list[dict]:
        """Lock 'pending' rows whose worker never picked them up (created_at-based)."""
        rows = self._conn.execute(
            text(
                """
                SELECT * FROM schedule_runs
                WHERE status = 'pending'
                  AND started_at IS NULL
                  AND created_at < now() - make_interval(mins => :age)
                ORDER BY created_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"age": int(age_minutes), "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def cleanup_older_than(
        self,
        ttl_days: int,
        *,
        keep_recent_per_schedule: int = 50,
    ) -> int:
        """Trim run rows older than ``ttl_days``, keeping the recent log slice."""
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        result = self._conn.execute(
            text(
                """
                DELETE FROM schedule_runs
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY schedule_id
                                   ORDER BY scheduled_for DESC
                               ) AS rn,
                               created_at
                        FROM schedule_runs
                    ) ranked
                    WHERE ranked.rn > :keep
                      AND ranked.created_at < now() - make_interval(days => :ttl)
                )
                """
            ),
            {"keep": int(keep_recent_per_schedule), "ttl": int(ttl_days)},
        )
        return int(result.rowcount or 0)
