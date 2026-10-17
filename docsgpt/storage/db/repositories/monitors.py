"""Repository for monitors: a ``schedules`` row (``trigger_type = 'monitor'``) plus its ``monitors`` side row.

The schedule carries what the dispatcher already understands (status,
``next_run_at``, ``end_at`` for expiry, the failure counter, the token
budget) and the monitor row what only a monitor needs (spec, state, the
bound approval, counters). Reads join the two; the monitor id is the
schedule id.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes

#: Columns of ``monitors`` a caller may set through :meth:`MonitorsRepository.update`.
_MONITOR_FIELDS = frozenset(
    {
        "description", "monitor_spec", "monitor_state", "approval", "interval_seconds", "check_count",
        "wake_count", "max_wakes", "judge_tokens", "last_checked_at", "last_changed_at", "last_woken_at",
        "last_error", "unreachable_since", "paused_reason",
    }
)
_JSON_FIELDS = frozenset({"monitor_spec", "monitor_state", "approval"})

_SELECT = """
    SELECT m.*, m.schedule_id AS id, s.status, s.next_run_at, s.end_at, s.instruction AS on_match,
           s.consecutive_failure_count, s.token_budget, s.created_via, s.agent_id AS schedule_agent_id
    FROM monitors m JOIN schedules s ON s.id = m.schedule_id
"""

#: Schedule statuses a monitor counts against the per-user cap in.
LIVE_STATUSES = ("active", "paused")


def _dump(value: Any) -> Optional[str]:
    """Serialize ``value`` for a jsonb CAST, stripping NULs Postgres rejects."""
    if value is None:
        return None
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


class MonitorsRepository:
    """Create, read and settle monitors."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------ create

    def create(
        self,
        *,
        user_id: str,
        conversation_id: str,
        agent_id: Optional[str],
        description: str,
        source_type: str,
        spec: Dict[str, Any],
        on_match: str,
        end_at: datetime,
        next_run_at: Optional[datetime],
        max_wakes: int,
        interval_seconds: Optional[int] = None,
        state: Optional[Dict[str, Any]] = None,
        approval: Optional[Dict[str, Any]] = None,
        token_budget: Optional[int] = None,
        check_count: int = 0,
        last_checked_at: Optional[datetime] = None,
    ) -> dict:
        """Insert the schedule and its monitor row; returns the joined row.

        Args:
            user_id: The owner (the conversation's user).
            conversation_id: The conversation a match wakes.
            agent_id: The conversation's agent, or None in an agentless chat.
            description: What is watched, shown in every notification.
            source_type: ``webpage``, ``tool``, ``ingest``, ``webhook`` or ``approval``.
            spec: The validated monitor spec.
            on_match: What the woken agent should do (the schedule's instruction).
            end_at: Expiry.
            next_run_at: The first tick (polled), or the expiry (event-driven).
            max_wakes: Wakes before the monitor finishes.
            interval_seconds: Seconds between polled checks.
            state: The baseline check state.
            approval: The bound creation-time approval of a tool source.
            token_budget: Tokens the condition judge may use.
            check_count: Checks done at creation (the baseline counts as one).
            last_checked_at: When the baseline was taken.

        Returns:
            The monitor row, joined with its schedule.
        """
        schedule = self._conn.execute(
            text(
                """
                INSERT INTO schedules (
                    user_id, agent_id, trigger_type, instruction, name, status, timezone,
                    next_run_at, end_at, tool_allowlist, token_budget, origin_conversation_id, created_via
                ) VALUES (
                    :user_id, CAST(:agent_id AS uuid), 'monitor', :instruction, :name, 'active', 'UTC',
                    :next_run_at, :end_at, CAST(:allowlist AS jsonb), :token_budget,
                    CAST(:conversation_id AS uuid), 'chat'
                ) RETURNING id
                """
            ),
            {
                "user_id": user_id,
                "agent_id": str(agent_id) if agent_id else None,
                "instruction": strip_null_bytes(on_match or ""),
                "name": strip_null_bytes(description)[:200],
                "next_run_at": next_run_at,
                "end_at": end_at,
                # Only a call the user approved may run approval-gated, unattended.
                "allowlist": json.dumps(
                    [approval["tool_id"]] if approval and approval.get("tool_id") and approval.get("required") else []
                ),
                "token_budget": token_budget,
                "conversation_id": str(conversation_id),
            },
        ).fetchone()
        monitor_id = str(schedule[0])
        self._conn.execute(
            text(
                """
                INSERT INTO monitors (
                    schedule_id, user_id, conversation_id, agent_id, description, source_type,
                    monitor_spec, monitor_state, approval, interval_seconds, max_wakes,
                    check_count, last_checked_at
                ) VALUES (
                    CAST(:id AS uuid), :user_id, CAST(:conversation_id AS uuid), CAST(:agent_id AS uuid),
                    :description, :source_type, CAST(:spec AS jsonb), CAST(:state AS jsonb),
                    CAST(:approval AS jsonb), :interval_seconds, :max_wakes, :check_count, :last_checked_at
                )
                """
            ),
            {
                "id": monitor_id,
                "user_id": user_id,
                "conversation_id": str(conversation_id),
                "agent_id": str(agent_id) if agent_id else None,
                "description": strip_null_bytes(description),
                "source_type": source_type,
                "spec": _dump(spec),
                "state": _dump(state or {}),
                "approval": _dump(approval),
                "interval_seconds": interval_seconds,
                "max_wakes": int(max_wakes),
                "check_count": int(check_count),
                "last_checked_at": last_checked_at,
            },
        )
        return self.get_internal(monitor_id) or {}

    # ------------------------------------------------------------------ reads

    def get_internal(self, monitor_id: str) -> Optional[dict]:
        """A monitor by id with no ownership check (workers only)."""
        if not looks_like_uuid(str(monitor_id)):
            return None
        row = self._conn.execute(
            text(_SELECT + " WHERE m.schedule_id = CAST(:id AS uuid)"), {"id": str(monitor_id)}
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, monitor_id: str, user_id: str) -> Optional[dict]:
        """An owned monitor, or None when missing or someone else's."""
        if not looks_like_uuid(str(monitor_id)):
            return None
        row = self._conn.execute(
            text(_SELECT + " WHERE m.schedule_id = CAST(:id AS uuid) AND m.user_id = :user_id"),
            {"id": str(monitor_id), "user_id": user_id},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def lock(self, monitor_id: str) -> Optional[dict]:
        """A monitor with its schedule row locked for the rest of the transaction."""
        if not looks_like_uuid(str(monitor_id)):
            return None
        locked = self._conn.execute(
            text("SELECT id FROM schedules WHERE id = CAST(:id AS uuid) AND trigger_type = 'monitor' FOR UPDATE"),
            {"id": str(monitor_id)},
        ).fetchone()
        if locked is None:
            return None
        return self.get_internal(str(monitor_id))

    def list_for_user(
        self,
        user_id: str,
        *,
        statuses: Optional[Iterable[str]] = None,
        conversation_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[dict]:
        """A user's monitors, newest first.

        Args:
            user_id: The owner.
            statuses: Schedule statuses to keep; None keeps all.
            conversation_id: Only this conversation's monitors.
            limit: Most rows returned.

        Returns:
            The joined rows.
        """
        sql = _SELECT + " WHERE m.user_id = :user_id"
        params: Dict[str, Any] = {"user_id": user_id, "limit": int(limit)}
        if conversation_id:
            if not looks_like_uuid(str(conversation_id)):
                return []
            sql += " AND m.conversation_id = CAST(:cid AS uuid)"
            params["cid"] = str(conversation_id)
        if statuses is not None:
            status_list = [str(s) for s in statuses]
            if not status_list:
                return []
            sql += " AND s.status = ANY(:statuses)"
            params["statuses"] = status_list
        sql += " ORDER BY m.created_at DESC LIMIT :limit"
        return [row_to_dict(r) for r in self._conn.execute(text(sql), params).fetchall()]

    def lock_user(self, user_id: str) -> None:
        """Serialize monitor creation for one user until the transaction ends (the per-user cap)."""
        self._conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('monitors:' || :user_id, 0))"),
            {"user_id": user_id},
        )

    def count_live_for_user(self, user_id: str) -> int:
        """Active or paused monitors the user has (the per-user cap)."""
        value = self._conn.execute(
            text(
                "SELECT COUNT(*) FROM schedules s JOIN monitors m ON m.schedule_id = s.id "
                "WHERE s.user_id = :user_id AND s.trigger_type = 'monitor' AND s.status IN ('active', 'paused')"
            ),
            {"user_id": user_id},
        ).scalar()
        return int(value or 0)

    def find_ingest_monitors(self, user_id: str, source_id: str) -> List[dict]:
        """Active ingest monitors of a user watching ``source_id``."""
        rows = self._conn.execute(
            text(
                _SELECT
                + " WHERE m.user_id = :user_id AND m.source_type = 'ingest' AND s.status = 'active' "
                "AND m.monitor_spec->'source'->>'source_id' = :source_id"
            ),
            {"user_id": user_id, "source_id": str(source_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------ writes

    def update(self, monitor_id: str, fields: Dict[str, Any]) -> None:
        """Set whitelisted ``monitors`` columns."""
        filtered = {k: v for k, v in fields.items() if k in _MONITOR_FIELDS}
        if not filtered:
            return
        parts: List[str] = []
        params: Dict[str, Any] = {"id": str(monitor_id)}
        for key, value in filtered.items():
            if key in _JSON_FIELDS:
                parts.append(f"{key} = CAST(:{key} AS jsonb)")
                params[key] = _dump(value)
            else:
                parts.append(f"{key} = :{key}")
                params[key] = strip_null_bytes(value) if isinstance(value, str) else value
        self._conn.execute(
            text("UPDATE monitors SET " + ", ".join(parts) + " WHERE schedule_id = CAST(:id AS uuid)"), params
        )

    def add_wake(self, monitor_id: str, when: datetime) -> int:
        """Count one wake; returns the new ``wake_count``."""
        row = self._conn.execute(
            text(
                "UPDATE monitors SET wake_count = wake_count + 1, last_woken_at = :when "
                "WHERE schedule_id = CAST(:id AS uuid) RETURNING wake_count"
            ),
            {"id": str(monitor_id), "when": when},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def add_judge_tokens(self, monitor_id: str, tokens: int) -> int:
        """Add judge tokens; returns the new total."""
        row = self._conn.execute(
            text(
                "UPDATE monitors SET judge_tokens = judge_tokens + :tokens "
                "WHERE schedule_id = CAST(:id AS uuid) RETURNING judge_tokens"
            ),
            {"id": str(monitor_id), "tokens": max(0, int(tokens))},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def set_schedule(self, monitor_id: str, **fields: Any) -> bool:
        """Set ``status``, ``next_run_at`` and/or ``consecutive_failure_count`` on the monitor's schedule.

        Returns:
            True when the schedule exists.
        """
        allowed = {k: v for k, v in fields.items() if k in ("status", "next_run_at", "consecutive_failure_count")}
        if not allowed:
            return False
        parts = [f"{key} = :{key}" for key in allowed]
        result = self._conn.execute(
            text(
                "UPDATE schedules SET " + ", ".join(parts)
                + " WHERE id = CAST(:id AS uuid) AND trigger_type = 'monitor'"
            ),
            {"id": str(monitor_id), **allowed},
        )
        return (result.rowcount or 0) > 0

    def bump_failures(self, monitor_id: str) -> int:
        """Count one more consecutive source error; returns the new count."""
        row = self._conn.execute(
            text(
                "UPDATE schedules SET consecutive_failure_count = consecutive_failure_count + 1 "
                "WHERE id = CAST(:id AS uuid) RETURNING consecutive_failure_count"
            ),
            {"id": str(monitor_id)},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def finish(self, monitor_id: str, status: str, *, reason: Optional[str] = None) -> bool:
        """End or pause a monitor: ``completed``, ``cancelled`` or ``paused``.

        A finished monitor (completed or cancelled) drops its bound approval,
        so nothing may run its source again. Only a live monitor changes.

        Returns:
            True when the status changed.
        """
        if status not in ("completed", "cancelled", "paused"):
            raise ValueError(f"not a terminal or paused status: {status}")
        from_statuses = ["active"] if status == "paused" else ["active", "paused"]
        result = self._conn.execute(
            text(
                "UPDATE schedules SET status = :status, next_run_at = NULL "
                "WHERE id = CAST(:id AS uuid) AND trigger_type = 'monitor' AND status = ANY(:from_statuses)"
            ),
            {"id": str(monitor_id), "status": status, "from_statuses": from_statuses},
        )
        if not (result.rowcount or 0):
            return False
        fields: Dict[str, Any] = {"paused_reason": reason}
        if status != "paused":
            fields["approval"] = None
        self.update(monitor_id, fields)
        if status != "paused":
            self._conn.execute(
                text("UPDATE schedules SET tool_allowlist = '[]'::jsonb WHERE id = CAST(:id AS uuid)"),
                {"id": str(monitor_id)},
            )
        return True

    def resume(self, monitor_id: str, next_run_at: Optional[datetime]) -> bool:
        """Re-activate a paused monitor; clears its error streak.

        Returns:
            True when it was paused and is active now.
        """
        result = self._conn.execute(
            text(
                "UPDATE schedules SET status = 'active', next_run_at = :next_run_at, consecutive_failure_count = 0 "
                "WHERE id = CAST(:id AS uuid) AND trigger_type = 'monitor' AND status = 'paused' "
                "AND (end_at IS NULL OR end_at > now())"
            ),
            {"id": str(monitor_id), "next_run_at": next_run_at},
        )
        if not (result.rowcount or 0):
            return False
        self.update(monitor_id, {"paused_reason": None, "unreachable_since": None, "last_error": None})
        return True

    # ------------------------------------------------------------------ tick lease

    def acquire_tick(self, monitor_id: str, *, stale_seconds: int) -> bool:
        """Take the monitor's tick lease, so two ticks of one monitor never overlap.

        Args:
            monitor_id: The monitor.
            stale_seconds: A lease older than this belongs to a tick that died.

        Returns:
            True when this caller holds the lease now.
        """
        row = self._conn.execute(
            text(
                "UPDATE monitors SET tick_started_at = now() WHERE schedule_id = CAST(:id AS uuid) "
                "AND (tick_started_at IS NULL OR tick_started_at < now() - make_interval(secs => :stale)) "
                "RETURNING schedule_id"
            ),
            {"id": str(monitor_id), "stale": int(stale_seconds)},
        ).fetchone()
        return row is not None

    def release_tick(self, monitor_id: str) -> None:
        """Give the tick lease back."""
        self._conn.execute(
            text("UPDATE monitors SET tick_started_at = NULL WHERE schedule_id = CAST(:id AS uuid)"),
            {"id": str(monitor_id)},
        )
