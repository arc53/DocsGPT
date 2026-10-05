"""Repository for ``background_jobs``: tool calls a turn handed off.

Every state change is a conditional update, so the processes that touch a
job (the thread or worker running it, the reconciler, ``check_job``, the
continuation task) can race without corrupting it: a final status is written
once, and a final result is delivered once (``claim_delivery``).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional, Sequence, Tuple

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes

#: Statuses a job ends in. ``lost`` is reported to models as ``failed``.
FINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "lost"})

#: Every runner, for sweeps that do not filter on one.
ALL_RUNNERS: Tuple[str, ...] = ("inprocess", "celery", "sandbox", "mcp")


def _dump(value: Any) -> Optional[str]:
    """Serialize ``value`` for a jsonb CAST, stripping NULs Postgres rejects."""
    if value is None:
        return None
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


class BackgroundJobsRepository:
    """Reads and conditional writes on ``background_jobs``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Create and read
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        user_id: str,
        tool_name: str,
        action_name: str,
        max_seconds: int,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        origin_message_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        kind: str = "tool_call",
        args: Optional[dict] = None,
        runner: str = "inprocess",
        lease_owner: Optional[str] = None,
        auto_resume: bool = True,
        watch: Optional[dict] = None,
        external: Optional[dict] = None,
        output_tail: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> Tuple[dict, bool]:
        """Insert a ``working`` job, or return the row this call already has.

        Args:
            user_id: The job's owner.
            tool_name: The tool's name (``code_executor``).
            action_name: The action called (``run_code``).
            max_seconds: Hard lifetime; ``deadline_at`` is now plus this.
            conversation_id: The conversation the job reports back to.
            workflow_run_id: The workflow run, for a job with no conversation.
            origin_message_id: The turn that started the job.
            tool_call_id: The turn-scoped call key; unique per conversation.
            agent_id: The agent the turn ran.
            kind: ``tool_call``, ``code_exec``, ``mcp_task`` or ``monitor_tick``.
            args: The call's arguments, secrets already redacted.
            runner: Who runs it: ``inprocess``, ``celery``, ``sandbox``, ``mcp``.
            lease_owner: The process holding the lease (in-process runners).
            auto_resume: Whether the final result resumes the conversation.
            watch: The call's ``watch`` spec.
            external: Runner handles (sandbox, session, command ids).
            output_tail: Output seen so far.
            status_message: A short human-readable state.

        Returns:
            ``(row, created)``; ``created`` is False when the call already had a job.
        """
        params = {
            "user_id": user_id,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "workflow_run_id": str(workflow_run_id) if workflow_run_id else None,
            "origin_message_id": str(origin_message_id) if origin_message_id else None,
            "tool_call_id": tool_call_id,
            "agent_id": str(agent_id) if agent_id and looks_like_uuid(str(agent_id)) else None,
            "tool_name": tool_name,
            "action_name": action_name,
            "kind": kind,
            "args": _dump(args or {}),
            "runner": runner,
            "lease_owner": lease_owner,
            "auto_resume": bool(auto_resume),
            "watch": _dump(watch),
            "external": _dump(external or {}),
            "output_tail": strip_null_bytes(output_tail) if output_tail else None,
            "status_message": status_message,
            "max_seconds": int(max_seconds),
        }
        row = self._conn.execute(
            text(
                """
                INSERT INTO background_jobs (
                    user_id, conversation_id, workflow_run_id, origin_message_id,
                    tool_call_id, agent_id, tool_name, action_name, kind, args,
                    runner, lease_owner, auto_resume, watch, external, output_tail,
                    status_message, deadline_at
                ) VALUES (
                    :user_id, CAST(:conversation_id AS uuid), CAST(:workflow_run_id AS uuid),
                    CAST(:origin_message_id AS uuid), :tool_call_id, CAST(:agent_id AS uuid),
                    :tool_name, :action_name, :kind, CAST(:args AS jsonb), :runner, :lease_owner,
                    :auto_resume, CAST(:watch AS jsonb), CAST(:external AS jsonb), :output_tail,
                    :status_message, now() + make_interval(secs => :max_seconds)
                )
                ON CONFLICT ON CONSTRAINT background_jobs_conversation_call_uidx DO NOTHING
                RETURNING *
                """
            ),
            params,
        ).fetchone()
        if row is not None:
            return row_to_dict(row), True
        existing = self._conn.execute(
            text(
                "SELECT * FROM background_jobs WHERE conversation_id = CAST(:conversation_id AS uuid) "
                "AND tool_call_id = :tool_call_id"
            ),
            params,
        ).fetchone()
        return row_to_dict(existing), False

    def get(self, job_id: str, *, user_id: Optional[str] = None) -> Optional[dict]:
        """Fetch a job by id, scoped to ``user_id`` when given."""
        if not looks_like_uuid(job_id):
            return None
        sql = "SELECT * FROM background_jobs WHERE id = CAST(:id AS uuid)"
        params: dict = {"id": str(job_id)}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        row = self._conn.execute(text(sql), params).fetchone()
        return row_to_dict(row) if row is not None else None

    def get_in_conversation(self, job_id: str, user_id: str, conversation_id: str) -> Optional[dict]:
        """Fetch a job only if it belongs to this user and conversation."""
        if not looks_like_uuid(job_id) or not looks_like_uuid(conversation_id):
            return None
        row = self._conn.execute(
            text(
                "SELECT * FROM background_jobs WHERE id = CAST(:id AS uuid) AND user_id = :user_id "
                "AND conversation_id = CAST(:conversation_id AS uuid)"
            ),
            {"id": str(job_id), "user_id": user_id, "conversation_id": str(conversation_id)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_conversation(self, conversation_id: str, user_id: str, *, limit: int = 20) -> list[dict]:
        """A conversation's jobs, newest first."""
        if not looks_like_uuid(conversation_id):
            return []
        rows = self._conn.execute(
            text(
                "SELECT * FROM background_jobs WHERE conversation_id = CAST(:conversation_id AS uuid) "
                "AND user_id = :user_id ORDER BY created_at DESC LIMIT :limit"
            ),
            {"conversation_id": str(conversation_id), "user_id": user_id, "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_working(self, *, user_id: Optional[str] = None, conversation_id: Optional[str] = None) -> int:
        """Running jobs for a user and/or a conversation."""
        clauses = ["status = 'working'"]
        params: dict = {}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if conversation_id is not None:
            if not looks_like_uuid(conversation_id):
                return 0
            clauses.append("conversation_id = CAST(:conversation_id AS uuid)")
            params["conversation_id"] = str(conversation_id)
        sql = f"SELECT count(*) FROM background_jobs WHERE {' AND '.join(clauses)}"
        return int(self._conn.execute(text(sql), params).scalar() or 0)

    # ------------------------------------------------------------------
    # Liveness and progress
    # ------------------------------------------------------------------

    def heartbeat(self, lease_owner: str) -> int:
        """Stamp ``heartbeat_at`` on every running job this process holds."""
        result = self._conn.execute(
            text(
                "UPDATE background_jobs SET heartbeat_at = now() "
                "WHERE lease_owner = :owner AND status = 'working'"
            ),
            {"owner": lease_owner},
        )
        return result.rowcount or 0

    def touch(self, job_id: str) -> bool:
        """Stamp one running job's heartbeat (a poller's tick)."""
        result = self._conn.execute(
            text(
                "UPDATE background_jobs SET heartbeat_at = now() "
                "WHERE id = CAST(:id AS uuid) AND status = 'working'"
            ),
            {"id": str(job_id)},
        )
        return (result.rowcount or 0) > 0

    def update_progress(
        self,
        job_id: str,
        *,
        progress: Optional[dict] = None,
        output_tail: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> bool:
        """Record progress on a running job; a finished job is left alone."""
        sets = ["last_updated_at = now()", "heartbeat_at = now()"]
        params: dict = {"id": str(job_id)}
        if progress is not None:
            sets.append("progress = progress || CAST(:progress AS jsonb)")
            params["progress"] = _dump(progress)
        if output_tail is not None:
            sets.append("output_tail = :output_tail")
            params["output_tail"] = strip_null_bytes(output_tail)
        if status_message is not None:
            sets.append("status_message = :status_message")
            params["status_message"] = status_message
        result = self._conn.execute(
            text(
                f"UPDATE background_jobs SET {', '.join(sets)} "
                "WHERE id = CAST(:id AS uuid) AND status = 'working'"
            ),
            params,
        )
        return (result.rowcount or 0) > 0

    def set_runner(
        self,
        job_id: str,
        *,
        runner: str,
        external: Optional[dict] = None,
        lease_owner: Optional[str] = None,
    ) -> bool:
        """Move a running job to another runner, merging its handles into ``external``."""
        result = self._conn.execute(
            text(
                "UPDATE background_jobs SET runner = :runner, lease_owner = :lease_owner, "
                "external = external || CAST(:external AS jsonb), heartbeat_at = now(), "
                "last_updated_at = now() WHERE id = CAST(:id AS uuid) AND status = 'working'"
            ),
            {"id": str(job_id), "runner": runner, "lease_owner": lease_owner, "external": _dump(external or {})},
        )
        return (result.rowcount or 0) > 0

    def merge_external(self, job_id: str, fields: dict) -> bool:
        """Merge ``fields`` into a job's ``external`` handles."""
        result = self._conn.execute(
            text(
                "UPDATE background_jobs SET external = external || CAST(:fields AS jsonb), "
                "last_updated_at = now() WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(job_id), "fields": _dump(fields)},
        )
        return (result.rowcount or 0) > 0

    def bump_attempts(self, job_id: str) -> int:
        """Count one more attempt at a job (a re-enqueued poller); returns the new count."""
        value = self._conn.execute(
            text(
                "UPDATE background_jobs SET attempts = attempts + 1, heartbeat_at = now() "
                "WHERE id = CAST(:id AS uuid) RETURNING attempts"
            ),
            {"id": str(job_id)},
        ).scalar()
        return int(value or 0)

    # ------------------------------------------------------------------
    # Terminal writes
    # ------------------------------------------------------------------

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        retention_days: int,
        result: Optional[dict] = None,
        error: Optional[dict] = None,
        status_message: Optional[str] = None,
        output_tail: Optional[str] = None,
    ) -> Optional[dict]:
        """Write a running job's final state, once.

        Args:
            job_id: The job.
            status: ``completed``, ``failed``, ``cancelled`` or ``lost``.
            retention_days: Days to keep the finished row.
            result: The final tool result, bounded by the caller.
            error: What went wrong, for a failed or lost job.
            status_message: A short human-readable state.
            output_tail: The last output seen.

        Returns:
            The finished row, or None when the job was not running (already final).

        Raises:
            ValueError: ``status`` is not a final status.
        """
        if status not in FINAL_STATUSES:
            raise ValueError(f"not a final job status: {status!r}")
        row = self._conn.execute(
            text(
                """
                UPDATE background_jobs SET
                    status = :status,
                    result = COALESCE(CAST(:result AS jsonb), result),
                    error = COALESCE(CAST(:error AS jsonb), error),
                    status_message = COALESCE(:status_message, status_message),
                    output_tail = COALESCE(:output_tail, output_tail),
                    finished_at = now(),
                    last_updated_at = now(),
                    expires_at = now() + make_interval(days => :retention_days)
                WHERE id = CAST(:id AS uuid) AND status = 'working'
                RETURNING *
                """
            ),
            {
                "id": str(job_id),
                "status": status,
                "result": _dump(result),
                "error": _dump(error),
                "status_message": status_message,
                "output_tail": strip_null_bytes(output_tail) if output_tail else None,
                "retention_days": int(retention_days),
            },
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def request_cancel(self, job_id: str, user_id: str) -> Optional[dict]:
        """Ask a job to stop; the first request's time is kept. Returns the row."""
        if not looks_like_uuid(job_id):
            return None
        row = self._conn.execute(
            text(
                "UPDATE background_jobs SET cancel_requested_at = COALESCE(cancel_requested_at, now()), "
                "last_updated_at = now() WHERE id = CAST(:id AS uuid) AND user_id = :user_id RETURNING *"
            ),
            {"id": str(job_id), "user_id": user_id},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def claim_delivery(
        self,
        job_id: str,
        to_state: str,
        *,
        from_states: Sequence[str] = ("pending",),
    ) -> Optional[dict]:
        """Move a final job's result from an undelivered state to ``to_state``, exactly once.

        ``check_job``, a continuation turn and the user's next message all
        race for a finished result; whichever claims it first delivers it.

        Returns:
            The claimed row, or None when the job is not final or was already claimed.
        """
        if not looks_like_uuid(job_id):
            return None
        row = self._conn.execute(
            text(
                "UPDATE background_jobs SET delivery_state = :to_state, delivered_at = now() "
                "WHERE id = CAST(:id AS uuid) AND delivery_state = ANY(:from_states) "
                "AND status <> 'working' RETURNING *"
            ),
            {"id": str(job_id), "to_state": to_state, "from_states": list(from_states)},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def release_delivery(self, job_id: str, from_state: str) -> bool:
        """Put a claimed result back to ``pending`` (a continuation that could not run)."""
        result = self._conn.execute(
            text(
                "UPDATE background_jobs SET delivery_state = 'pending', delivered_at = NULL "
                "WHERE id = CAST(:id AS uuid) AND delivery_state = :from_state"
            ),
            {"id": str(job_id), "from_state": from_state},
        )
        return (result.rowcount or 0) > 0

    def set_delivery_state(self, job_id: str, state: str) -> bool:
        """Overwrite a job's delivery state (a continuation's final verdict on it)."""
        result = self._conn.execute(
            text(
                "UPDATE background_jobs SET delivery_state = :state, delivered_at = COALESCE(delivered_at, now()) "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(job_id), "state": state},
        )
        return (result.rowcount or 0) > 0

    def set_followup(self, job_id: str, message_id: str) -> bool:
        """Link a job to the message that delivered its result."""
        result = self._conn.execute(
            text("UPDATE background_jobs SET followup_message_id = CAST(:mid AS uuid) WHERE id = CAST(:id AS uuid)"),
            {"id": str(job_id), "mid": str(message_id)},
        )
        return (result.rowcount or 0) > 0

    def claim_foldable(self, conversation_id: str, user_id: str) -> list[dict]:
        """Claim every finished, undelivered job of a conversation for the user's new message."""
        if not looks_like_uuid(conversation_id):
            return []
        rows = self._conn.execute(
            text(
                "UPDATE background_jobs SET delivery_state = 'folded', delivered_at = now() "
                "WHERE conversation_id = CAST(:conversation_id AS uuid) AND user_id = :user_id "
                "AND status <> 'working' AND delivery_state = 'pending' RETURNING *"
            ),
            {"conversation_id": str(conversation_id), "user_id": user_id},
        ).fetchall()
        return sorted((row_to_dict(r) for r in rows), key=lambda r: str(r.get("finished_at") or ""))

    # ------------------------------------------------------------------
    # Sweeps
    # ------------------------------------------------------------------

    def find_stale_working(
        self, *, stale_seconds: int, runners: Iterable[str] = ALL_RUNNERS, limit: int = 100
    ) -> list[dict]:
        """Lock running jobs whose heartbeat is older than ``stale_seconds``."""
        rows = self._conn.execute(
            text(
                "SELECT * FROM background_jobs WHERE status = 'working' AND runner = ANY(:runners) "
                "AND heartbeat_at < now() - make_interval(secs => :stale) "
                "ORDER BY heartbeat_at ASC LIMIT :limit FOR UPDATE SKIP LOCKED"
            ),
            {"stale": int(stale_seconds), "runners": list(runners), "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def find_past_deadline(self, *, grace_seconds: int, limit: int = 100) -> list[dict]:
        """Lock running jobs past their deadline by more than ``grace_seconds``."""
        rows = self._conn.execute(
            text(
                "SELECT * FROM background_jobs WHERE status = 'working' "
                "AND deadline_at < now() - make_interval(secs => :grace) "
                "ORDER BY deadline_at ASC LIMIT :limit FOR UPDATE SKIP LOCKED"
            ),
            {"grace": int(grace_seconds), "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def find_undelivered(self, *, older_than_seconds: int, limit: int = 100) -> list[dict]:
        """Finished jobs that should have resumed their conversation but have not."""
        rows = self._conn.execute(
            text(
                "SELECT * FROM background_jobs WHERE status <> 'working' AND delivery_state = 'pending' "
                "AND auto_resume AND conversation_id IS NOT NULL "
                "AND finished_at < now() - make_interval(secs => :age) "
                "ORDER BY finished_at ASC LIMIT :limit"
            ),
            {"age": int(older_than_seconds), "limit": int(limit)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def cleanup_expired(self) -> int:
        """Delete finished jobs past their retention."""
        result = self._conn.execute(
            text("DELETE FROM background_jobs WHERE status <> 'working' AND expires_at < now()")
        )
        return result.rowcount or 0
