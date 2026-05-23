"""Repository for the ``schedules`` table (CRUD + dispatcher claim query)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


_ALLOWED_UPDATES = frozenset(
    {
        "name", "instruction", "status", "cron", "run_at", "timezone",
        "next_run_at", "last_run_at", "end_at", "tool_allowlist",
        "model_id", "token_budget", "consecutive_failure_count",
        "origin_conversation_id",
    }
)


class SchedulesRepository:
    """CRUD + dispatcher hot path for ``schedules``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        agent_id: Optional[str],
        trigger_type: str,
        instruction: str,
        *,
        cron: Optional[str] = None,
        run_at: Optional[datetime] = None,
        timezone: str = "UTC",
        next_run_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        name: Optional[str] = None,
        tool_allowlist: Optional[Iterable[str]] = None,
        model_id: Optional[str] = None,
        token_budget: Optional[int] = None,
        origin_conversation_id: Optional[str] = None,
        created_via: str = "ui",
        status: str = "active",
    ) -> dict:
        """Insert a new schedule and return the populated row."""
        params = {
            "user_id": user_id,
            "agent_id": str(agent_id) if agent_id else None,
            "trigger_type": trigger_type,
            "instruction": instruction,
            "cron": cron,
            "run_at": run_at,
            "tz": timezone,
            "next_run_at": next_run_at,
            "end_at": end_at,
            "name": name,
            "allowlist": json.dumps(list(tool_allowlist or [])),
            "model_id": model_id,
            "token_budget": int(token_budget) if token_budget is not None else None,
            "origin_conversation_id": (
                str(origin_conversation_id) if origin_conversation_id else None
            ),
            "created_via": created_via,
            "status": status,
        }
        row = self._conn.execute(
            text(
                """
                INSERT INTO schedules (
                    user_id, agent_id, trigger_type, instruction, status,
                    cron, run_at, timezone, next_run_at, end_at, name,
                    tool_allowlist, model_id, token_budget,
                    origin_conversation_id, created_via
                ) VALUES (
                    :user_id,
                    CAST(:agent_id AS uuid),
                    :trigger_type,
                    :instruction,
                    :status,
                    :cron,
                    :run_at,
                    :tz,
                    :next_run_at,
                    :end_at,
                    :name,
                    CAST(:allowlist AS jsonb),
                    :model_id,
                    :token_budget,
                    CAST(:origin_conversation_id AS uuid),
                    :created_via
                ) RETURNING *
                """
            ),
            params,
        ).fetchone()
        return row_to_dict(row)

    def get(self, schedule_id: str, user_id: str) -> Optional[dict]:
        """Fetch an owned schedule (None when missing or owned by another)."""
        row = self._conn.execute(
            text(
                "SELECT * FROM schedules "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": str(schedule_id), "user_id": user_id},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get_internal(self, schedule_id: str) -> Optional[dict]:
        """Fetch a schedule with no ownership scoping (worker-only)."""
        row = self._conn.execute(
            text("SELECT * FROM schedules WHERE id = CAST(:id AS uuid)"),
            {"id": str(schedule_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get_for_update(
        self, schedule_id: str, user_id: str,
    ) -> Optional[dict]:
        """Owned fetch with FOR UPDATE; closes the Run-Now TOCTOU."""
        row = self._conn.execute(
            text(
                "SELECT * FROM schedules "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id "
                "FOR UPDATE"
            ),
            {"id": str(schedule_id), "user_id": user_id},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_agent(
        self,
        agent_id: str,
        user_id: str,
        *,
        statuses: Optional[Iterable[str]] = None,
        trigger_type: Optional[str] = None,
    ) -> list[dict]:
        """Owned schedules for an agent, newest-created first."""
        sql = (
            "SELECT * FROM schedules "
            "WHERE agent_id = CAST(:agent_id AS uuid) AND user_id = :user_id"
        )
        params: dict[str, Any] = {"agent_id": str(agent_id), "user_id": user_id}
        if statuses is not None:
            status_list = [str(s) for s in statuses]
            if not status_list:
                return []
            placeholders = ", ".join(f":s{i}" for i, _ in enumerate(status_list))
            sql += f" AND status IN ({placeholders})"
            for i, s in enumerate(status_list):
                params[f"s{i}"] = s
        if trigger_type:
            sql += " AND trigger_type = :trigger_type"
            params["trigger_type"] = trigger_type
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(text(sql), params).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_for_conversation(
        self,
        user_id: str,
        origin_conversation_id: str,
        *,
        statuses: Optional[Iterable[str]] = None,
        trigger_type: Optional[str] = None,
    ) -> list[dict]:
        """Owned agentless schedules anchored to an originating conversation."""
        sql = (
            "SELECT * FROM schedules "
            "WHERE user_id = :user_id "
            "AND agent_id IS NULL "
            "AND origin_conversation_id = CAST(:conv AS uuid)"
        )
        params: dict[str, Any] = {
            "user_id": user_id,
            "conv": str(origin_conversation_id),
        }
        if statuses is not None:
            status_list = [str(s) for s in statuses]
            if not status_list:
                return []
            placeholders = ", ".join(f":s{i}" for i, _ in enumerate(status_list))
            sql += f" AND status IN ({placeholders})"
            for i, s in enumerate(status_list):
                params[f"s{i}"] = s
        if trigger_type:
            sql += " AND trigger_type = :trigger_type"
            params["trigger_type"] = trigger_type
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(text(sql), params).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_for_user(self, user_id: str, *, limit: int = 200) -> list[dict]:
        """Owned schedules across all agents — admin / debugging path."""
        rows = self._conn.execute(
            text(
                "SELECT * FROM schedules WHERE user_id = :user_id "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"user_id": user_id, "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_active_for_user(self, user_id: str) -> int:
        """Active+paused schedules for quota enforcement."""
        scalar = self._conn.execute(
            text(
                "SELECT COUNT(*) FROM schedules "
                "WHERE user_id = :user_id AND status IN ('active', 'paused')"
            ),
            {"user_id": user_id},
        ).scalar()
        return int(scalar or 0)

    def list_due(self, *, limit: int = 100) -> list[dict]:
        """Lock and return schedules with ``next_run_at <= now()``."""
        rows = self._conn.execute(
            text(
                """
                SELECT * FROM schedules
                WHERE status = 'active'
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= now()
                  AND (end_at IS NULL OR next_run_at <= end_at)
                ORDER BY next_run_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def update(
        self,
        schedule_id: str,
        user_id: str,
        fields: dict,
    ) -> Optional[dict]:
        """Apply a whitelisted partial update; return the new row or None."""
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATES}
        if not filtered:
            return self.get(schedule_id, user_id)
        set_parts: list[str] = []
        params: dict[str, Any] = {"id": str(schedule_id), "user_id": user_id}
        for key, val in filtered.items():
            if key == "tool_allowlist":
                set_parts.append("tool_allowlist = CAST(:tool_allowlist AS jsonb)")
                params["tool_allowlist"] = json.dumps(list(val or []))
            elif key == "origin_conversation_id":
                set_parts.append(
                    "origin_conversation_id = CAST(:origin_conversation_id AS uuid)"
                )
                params["origin_conversation_id"] = str(val) if val else None
            else:
                set_parts.append(f"{key} = :{key}")
                params[key] = val
        sql = (
            "UPDATE schedules SET " + ", ".join(set_parts) +
            " WHERE id = CAST(:id AS uuid) AND user_id = :user_id "
            "RETURNING *"
        )
        row = self._conn.execute(text(sql), params).fetchone()
        return row_to_dict(row) if row is not None else None

    def update_internal(self, schedule_id: str, fields: dict) -> None:
        """Apply a whitelisted partial update from a worker context."""
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATES}
        if not filtered:
            return
        set_parts: list[str] = []
        params: dict[str, Any] = {"id": str(schedule_id)}
        for key, val in filtered.items():
            if key == "tool_allowlist":
                set_parts.append("tool_allowlist = CAST(:tool_allowlist AS jsonb)")
                params["tool_allowlist"] = json.dumps(list(val or []))
            elif key == "origin_conversation_id":
                set_parts.append(
                    "origin_conversation_id = CAST(:origin_conversation_id AS uuid)"
                )
                params["origin_conversation_id"] = str(val) if val else None
            else:
                set_parts.append(f"{key} = :{key}")
                params[key] = val
        sql = (
            "UPDATE schedules SET " + ", ".join(set_parts) +
            " WHERE id = CAST(:id AS uuid)"
        )
        self._conn.execute(text(sql), params)

    def cancel(self, schedule_id: str, user_id: str) -> bool:
        """Soft-cancel — flips ``status`` to ``cancelled`` and clears ``next_run_at``."""
        result = self._conn.execute(
            text(
                "UPDATE schedules SET status = 'cancelled', next_run_at = NULL "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id "
                "AND status NOT IN ('cancelled', 'completed')"
            ),
            {"id": str(schedule_id), "user_id": user_id},
        )
        return (result.rowcount or 0) > 0

    def delete(self, schedule_id: str, user_id: str) -> bool:
        """Hard-delete an owned schedule and its runs (FK cascade)."""
        result = self._conn.execute(
            text(
                "DELETE FROM schedules "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": str(schedule_id), "user_id": user_id},
        )
        return (result.rowcount or 0) > 0

    def bump_failure_count(self, schedule_id: str) -> int:
        """Increment ``consecutive_failure_count`` and return the new value."""
        row = self._conn.execute(
            text(
                "UPDATE schedules "
                "SET consecutive_failure_count = consecutive_failure_count + 1 "
                "WHERE id = CAST(:id AS uuid) "
                "RETURNING consecutive_failure_count"
            ),
            {"id": str(schedule_id)},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def reset_failure_count(self, schedule_id: str) -> None:
        """Reset the failure counter to 0 after a successful run."""
        self._conn.execute(
            text(
                "UPDATE schedules SET consecutive_failure_count = 0 "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(schedule_id)},
        )

    def autopause(self, schedule_id: str) -> bool:
        """Flip an active schedule to ``paused`` after repeated failures."""
        result = self._conn.execute(
            text(
                "UPDATE schedules SET status = 'paused', next_run_at = NULL "
                "WHERE id = CAST(:id AS uuid) AND status = 'active'"
            ),
            {"id": str(schedule_id)},
        )
        return (result.rowcount or 0) > 0
