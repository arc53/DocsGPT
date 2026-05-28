"""Append-only audit log for remote-device tool invocations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class DeviceAuditLogRepository:
    """Server-side canonical record of every remote-device invocation."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record_dispatch(
        self,
        *,
        device_id: str,
        user_id: str,
        invocation_id: str,
        command: str,
        approval_mode: str,
        decision: str,
        decision_reason: Optional[str],
        issued_at: datetime,
        action: str = "run_command",
        working_dir: Optional[str] = None,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> dict:
        row = self._conn.execute(
            text(
                """
                INSERT INTO device_audit_log (
                    device_id, user_id, agent_id, conversation_id,
                    invocation_id, action, command, working_dir,
                    approval_mode, decision, decision_reason, issued_at
                ) VALUES (
                    :device_id, :user_id, :agent_id, :conversation_id,
                    :invocation_id, :action, :command, :working_dir,
                    :approval_mode, :decision, :decision_reason, :issued_at
                ) RETURNING *
                """
            ),
            {
                "device_id": device_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "invocation_id": invocation_id,
                "action": action,
                "command": command,
                "working_dir": working_dir,
                "approval_mode": approval_mode,
                "decision": decision,
                "decision_reason": decision_reason,
                "issued_at": issued_at,
            },
        ).fetchone()
        return row_to_dict(row)

    def record_result(
        self,
        invocation_id: str,
        *,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        exit_code: Optional[int] = None,
        duration_ms: Optional[int] = None,
        stdout_sha256: Optional[str] = None,
        stderr_sha256: Optional[str] = None,
        stdout_bytes: Optional[int] = None,
        stderr_bytes: Optional[int] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update the dispatched row with execution outcome."""
        result = self._conn.execute(
            text(
                """
                UPDATE device_audit_log
                SET started_at    = COALESCE(:started_at, started_at),
                    finished_at   = COALESCE(:finished_at, finished_at),
                    exit_code     = COALESCE(:exit_code, exit_code),
                    duration_ms   = COALESCE(:duration_ms, duration_ms),
                    stdout_sha256 = COALESCE(:stdout_sha256, stdout_sha256),
                    stderr_sha256 = COALESCE(:stderr_sha256, stderr_sha256),
                    stdout_bytes  = COALESCE(:stdout_bytes, stdout_bytes),
                    stderr_bytes  = COALESCE(:stderr_bytes, stderr_bytes),
                    error         = COALESCE(:error, error)
                WHERE invocation_id = :invocation_id
                """
            ),
            {
                "invocation_id": invocation_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "stdout_sha256": stdout_sha256,
                "stderr_sha256": stderr_sha256,
                "stdout_bytes": stdout_bytes,
                "stderr_bytes": stderr_bytes,
                "error": error,
            },
        )
        return result.rowcount > 0

    def list_for_device(
        self, device_id: str, user_id: str, *, limit: int = 100
    ) -> list[dict]:
        result = self._conn.execute(
            text(
                """
                SELECT * FROM device_audit_log
                WHERE device_id = :device_id AND user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"device_id": device_id, "user_id": user_id, "limit": int(limit)},
        )
        return [row_to_dict(r) for r in result.fetchall()]
