"""Repository for the ``schedules`` table (CRUD + dispatcher claim query)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict


_ALLOWED_UPDATES = frozenset(
    {
        "name", "instruction", "status", "cron", "run_at", "timezone",
        "next_run_at", "last_run_at", "end_at", "tool_allowlist",
        "model_id", "token_budget", "consecutive_failure_count",
        "origin_conversation_id",
    }
)

#: The columns that decide when a schedule fires, with their SQL types.
_PLAN_FIELDS = {"cron": "text", "timezone": "text", "run_at": "timestamptz"}


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

    def lock_internal(self, schedule_id: str) -> Optional[dict]:
        """Fetch a schedule whoever it is stored under and lock the row (``FOR UPDATE``) until the transaction ends.

        Args:
            schedule_id: Schedule UUID.

        Returns:
            The row, or None when it doesn't exist.
        """
        row = self._conn.execute(
            text("SELECT * FROM schedules WHERE id = CAST(:id AS uuid) FOR UPDATE"),
            {"id": str(schedule_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def take_over(self, schedule_id: str, user_id: str) -> Optional[dict]:
        """Store a schedule under a new payer, who runs it from now on.

        The failure count starts afresh, and the chat it was set from is
        dropped: that chat stays its old setter's, and the runs would
        otherwise read its history into output the new payer sees. The
        status is left alone, so a schedule someone paused stays paused.
        A one-time task whose time has passed while it waited out its old
        payer's pause runs now rather than at its next check.

        Args:
            schedule_id: Schedule UUID.
            user_id: The new payer.

        Returns:
            The updated row, or None when no row matched.
        """
        row = self._conn.execute(
            text(
                "UPDATE schedules SET user_id = :user_id, consecutive_failure_count = 0, "
                "origin_conversation_id = NULL, "
                "next_run_at = CASE WHEN trigger_type = 'once' AND next_run_at IS NOT NULL "
                "THEN LEAST(next_run_at, GREATEST(run_at, now())) ELSE next_run_at END "
                "WHERE id = CAST(:id AS uuid) RETURNING *"
            ),
            {"id": str(schedule_id), "user_id": user_id},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def rearm_once(self, schedule_id: str, at: datetime) -> bool:
        """Give a one-time task skipped for its payer a next run, so it fires once the pause clears.

        Only an active one-time task the dispatcher has already taken (no
        next run) is re-armed: a person who paused, edited or ran it since
        keeps what they set.

        Args:
            schedule_id: Schedule UUID.
            at: When to check the pause again.

        Returns:
            True when the task was re-armed.
        """
        result = self._conn.execute(
            text(
                "UPDATE schedules SET next_run_at = :at WHERE id = CAST(:id AS uuid) "
                "AND trigger_type = 'once' AND status = 'active' AND next_run_at IS NULL"
            ),
            {"id": str(schedule_id), "at": at},
        )
        return (result.rowcount or 0) > 0

    def get_with_context(self, schedule_id: str, viewer: str) -> Optional[dict]:
        """One schedule with the extra keys of the lists (``list_for_owner_agents_with_context``).

        ``origin_conversation_name`` is filled only when the viewer set it:
        the chat a schedule came from stays with its setter.

        Args:
            schedule_id: Schedule UUID.
            viewer: Who reads it.

        Returns:
            The row with ``agent_name``, ``agent_image``, ``agent_user_id`` and
            ``origin_conversation_name``, or None when it doesn't exist.
        """
        row = self._conn.execute(
            text(
                """
                SELECT s.*, a.name AS agent_name, a.image AS agent_image,
                       a.user_id AS agent_user_id,
                       CASE WHEN s.user_id = :viewer THEN c.name END AS origin_conversation_name
                FROM schedules s
                LEFT JOIN agents a ON a.id = s.agent_id
                LEFT JOIN conversations c ON c.id = s.origin_conversation_id
                WHERE s.id = CAST(:id AS uuid)
                """
            ),
            {"id": str(schedule_id), "viewer": viewer},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_agent(
        self,
        agent_id: str,
        user_id: Optional[str],
        *,
        statuses: Optional[Iterable[str]] = None,
        trigger_type: Optional[str] = None,
    ) -> list[dict]:
        """Owned schedules for an agent, newest-created first.

        ``user_id`` None lists every user's schedule on the agent: a team
        agent's schedules are stored under the members who set them.
        """
        sql = "SELECT * FROM schedules WHERE agent_id = CAST(:agent_id AS uuid)"
        params: dict[str, Any] = {"agent_id": str(agent_id)}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
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
        else:
            # Monitors live on their own page (Settings -> Monitors).
            sql += " AND trigger_type <> 'monitor'"
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

    def list_owned_with_context(self, user_id: str, *, limit: int = 500) -> list[dict]:
        """Owned schedules across every agent, agentless ones included, newest first.

        Monitors are left out (they have their own page). Each row also
        carries ``agent_name`` / ``agent_image`` / ``agent_user_id`` (the
        agent's owner, who an image URL is signed for) and the originating
        chat's ``origin_conversation_name``, so a cross-agent list can group
        and label rows without a lookup per agent. ``agent_image`` is the raw
        storage value: callers must turn it into a URL before returning it.

        Live (active and paused) schedules come first, newest first, then
        finished ones: finished tasks are kept, so the newest of them would
        otherwise fill ``limit`` and hide an older live schedule. Live ones
        are capped per user (``SCHEDULE_MAX_PER_USER``), so they fit.

        Args:
            user_id: The owner.
            limit: Maximum rows returned.

        Returns:
            Schedule rows with the extra keys (``None`` when absent).
        """
        rows = self._conn.execute(
            text(
                """
                SELECT s.*, a.name AS agent_name, a.image AS agent_image,
                       a.user_id AS agent_user_id,
                       c.name AS origin_conversation_name
                FROM schedules s
                LEFT JOIN agents a ON a.id = s.agent_id
                LEFT JOIN conversations c ON c.id = s.origin_conversation_id
                WHERE s.user_id = :user_id AND s.trigger_type <> 'monitor'
                ORDER BY s.status IN ('active', 'paused') DESC, s.created_at DESC
                LIMIT :limit
                """
            ),
            {"user_id": user_id, "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_for_agents_with_context(self, agent_ids: Iterable[str], *, limit: int = 500) -> list[dict]:
        """The agent owners' schedules of these agents, with the same extra keys.

        For a team editor's cross-agent list: a schedule created on an agent's
        Schedules tab is stored under the agent's owner. A member's own chat
        task on the agent (stored under that member) is not returned.
        ``origin_conversation_name`` is always ``None``: the chat a schedule
        came from is the owner's own, and its title stays with them. Live
        schedules come first, as in ``list_owned_with_context``.

        Args:
            agent_ids: Agent UUIDs.
            limit: Maximum rows returned.

        Returns:
            Rows shaped like ``list_owned_with_context``.
        """
        ids = [str(a) for a in agent_ids if looks_like_uuid(str(a))]
        if not ids:
            return []
        rows = self._conn.execute(
            text(
                """
                SELECT s.*, a.name AS agent_name, a.image AS agent_image,
                       a.user_id AS agent_user_id,
                       NULL AS origin_conversation_name
                FROM schedules s
                JOIN agents a ON a.id = s.agent_id AND a.user_id = s.user_id
                WHERE s.agent_id = ANY(CAST(:ids AS uuid[]))
                  AND s.trigger_type <> 'monitor'
                ORDER BY s.status IN ('active', 'paused') DESC, s.created_at DESC
                LIMIT :limit
                """
            ),
            {"ids": ids, "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_for_owner_agents_with_context(
        self, owner_id: str, viewer: str, *, setter: Optional[str] = None, limit: int = 500,
    ) -> list[dict]:
        """Schedules on every agent ``owner_id`` owns (a team's), shaped like ``list_owned_with_context``.

        A team's agents carry schedules set by its members, each stored under
        whoever set it. ``origin_conversation_name`` is filled only on the
        viewer's own rows: the chat a schedule came from stays with its setter.

        Args:
            owner_id: The agents' owner (a team's principal).
            viewer: The member reading the list.
            setter: Only schedules this person set; None for everyone's.
            limit: Maximum rows returned.

        Returns:
            Schedule rows with the extra keys, live ones first, then newest first.
        """
        sql = """
            SELECT s.*, a.name AS agent_name, a.image AS agent_image,
                   a.user_id AS agent_user_id,
                   CASE WHEN s.user_id = :viewer THEN c.name END AS origin_conversation_name
            FROM schedules s
            JOIN agents a ON a.id = s.agent_id AND a.user_id = :owner
            LEFT JOIN conversations c ON c.id = s.origin_conversation_id
            WHERE s.trigger_type <> 'monitor'
        """
        params: dict[str, Any] = {"owner": owner_id, "viewer": viewer, "limit": int(limit)}
        if setter is not None:
            sql += " AND s.user_id = :setter"
            params["setter"] = setter
        sql += " ORDER BY s.status IN ('active', 'paused') DESC, s.created_at DESC LIMIT :limit"
        rows = self._conn.execute(text(sql), params).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_active_for_user(self, user_id: str) -> int:
        """Active+paused schedules for quota enforcement (monitors have their own cap)."""
        scalar = self._conn.execute(
            text(
                "SELECT COUNT(*) FROM schedules "
                "WHERE user_id = :user_id AND status IN ('active', 'paused') "
                "AND trigger_type <> 'monitor'"
            ),
            {"user_id": user_id},
        ).scalar()
        return int(scalar or 0)

    def any_live_for_agent(self, agent_id: str) -> bool:
        """Whether any user's active or paused schedule (a monitor included) runs the agent."""
        return self._conn.execute(
            text(
                "SELECT 1 FROM schedules WHERE agent_id = CAST(:agent_id AS uuid) "
                "AND status IN ('active', 'paused') LIMIT 1"
            ),
            {"agent_id": str(agent_id)},
        ).first() is not None

    def list_due(self, *, limit: int = 100) -> list[dict]:
        """Lock and return schedules with ``next_run_at <= now()`` (monitors tick through their own dispatch).

        A one-time task waiting for a Run now of it to end is left out, so a
        batch of them can't hold back other due schedules.
        """
        rows = self._conn.execute(
            text(
                """
                SELECT * FROM schedules
                WHERE status = 'active'
                  AND trigger_type <> 'monitor'
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= now()
                  AND (end_at IS NULL OR next_run_at <= end_at)
                  AND NOT (
                    trigger_type = 'once'
                    AND EXISTS (
                      SELECT 1 FROM schedule_runs r
                      WHERE r.schedule_id = schedules.id
                        AND r.status IN ('pending', 'running')
                        AND r.trigger_source = 'manual'
                    )
                  )
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
        *,
        pending_once_status: Optional[str] = None,
    ) -> Optional[dict]:
        """Apply a whitelisted partial update; return the new row or None.

        Args:
            schedule_id: Schedule UUID.
            user_id: The owner the row must belong to.
            fields: Columns to set; others are ignored.
            pending_once_status: When set, update only a one-time task still in
                this status that the dispatcher hasn't claimed (an active task
                must still have ``next_run_at``). Rescheduling uses it so a
                task dispatched, paused or cancelled since it was read is left
                alone, and ``None`` is returned instead.

        Returns:
            The updated row, or ``None`` when no row matched.
        """
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
        # A new timing, or a resume, starts a new plan: the calendar's
        # missed slots count from here (the dispatcher writes through
        # ``update_internal`` and never moves it). Compared with the stored
        # row (``SET`` reads the old values): the edit form resends the
        # timezone and cron it loaded, and a rename is no new plan.
        changes = [
            f"{key} IS DISTINCT FROM CAST(:{key} AS {_PLAN_FIELDS[key]})"
            for key in _PLAN_FIELDS.keys() & filtered.keys()
        ]
        if filtered.get("status") == "active":
            changes.append("status <> 'active'")
        if changes:
            set_parts.append(
                "plan_changed_at = CASE WHEN " + " OR ".join(changes) +
                " THEN now() ELSE plan_changed_at END"
            )
        guard = ""
        if pending_once_status is not None:
            guard = " AND trigger_type = 'once' AND status = :pending_status"
            params["pending_status"] = pending_once_status
            if pending_once_status == "active":
                guard += " AND next_run_at IS NOT NULL"
        sql = (
            "UPDATE schedules SET " + ", ".join(set_parts) +
            " WHERE id = CAST(:id AS uuid) AND user_id = :user_id" + guard +
            " RETURNING *"
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
        """Soft-cancel — flips ``status`` to ``cancelled`` and clears ``next_run_at``.

        Never a monitor's schedule: a monitor is cancelled through
        ``/api/monitors`` or ``monitor_cancel``, which also revoke its links
        and its approval.
        """
        result = self._conn.execute(
            text(
                "UPDATE schedules SET status = 'cancelled', next_run_at = NULL "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id "
                "AND status NOT IN ('cancelled', 'completed') AND trigger_type <> 'monitor'"
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
