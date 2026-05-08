"""Repository for ``tool_call_attempts``; executor's proposed/executed/failed writes."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.serialization import PGNativeJSONEncoder


class ToolCallAttemptsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record_proposed(
        self,
        call_id: str,
        tool_name: str,
        action_name: str,
        arguments: Any,
        *,
        tool_id: Optional[str] = None,
    ) -> bool:
        """Insert a ``proposed`` row before the tool executes.

        Returns True if a new row was created. ``ON CONFLICT DO NOTHING``
        guards against the LLM emitting a duplicate ``call_id``: the
        existing row stays put rather than a re-insert raising
        ``IntegrityError``.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO tool_call_attempts
                    (call_id, tool_id, tool_name, action_name, arguments, status)
                VALUES
                    (:call_id, CAST(:tool_id AS uuid), :tool_name,
                     :action_name, CAST(:arguments AS jsonb), 'proposed')
                ON CONFLICT (call_id) DO NOTHING
                """
            ),
            {
                "call_id": call_id,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "action_name": action_name,
                "arguments": json.dumps(arguments if arguments is not None else {}, cls=PGNativeJSONEncoder),
            },
        )
        return result.rowcount > 0

    def upsert_executed(
        self,
        call_id: str,
        tool_name: str,
        action_name: str,
        arguments: Any,
        result: Any,
        *,
        tool_id: Optional[str] = None,
        message_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
    ) -> None:
        """Insert OR upgrade a row to ``executed``.

        Used as a fallback when ``record_proposed`` failed (DB outage)
        and the tool ran anyway — preserves the journal so the
        reconciler can still see the attempt.
        """
        result_payload: dict = {"result": result}
        if artifact_id:
            result_payload["artifact_id"] = artifact_id
        self._conn.execute(
            text(
                """
                INSERT INTO tool_call_attempts
                    (call_id, tool_id, tool_name, action_name, arguments,
                     result, message_id, status)
                VALUES
                    (:call_id, CAST(:tool_id AS uuid), :tool_name,
                     :action_name, CAST(:arguments AS jsonb),
                     CAST(:result AS jsonb), CAST(:message_id AS uuid),
                     'executed')
                ON CONFLICT (call_id) DO UPDATE
                   SET status     = 'executed',
                       result     = EXCLUDED.result,
                       message_id = COALESCE(EXCLUDED.message_id, tool_call_attempts.message_id)
                """
            ),
            {
                "call_id": call_id,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "action_name": action_name,
                "arguments": json.dumps(arguments if arguments is not None else {}, cls=PGNativeJSONEncoder),
                "result": json.dumps(result_payload, cls=PGNativeJSONEncoder),
                "message_id": message_id,
            },
        )

    def mark_executed(
        self,
        call_id: str,
        result: Any,
        *,
        message_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
    ) -> bool:
        """Flip ``proposed`` → ``executed`` with the tool result.

        ``artifact_id`` (when present) is stored alongside ``result`` in
        the JSONB as audit data — the reconciler reads it for diagnostic
        alerts when escalating stuck rows to ``failed``.
        """
        result_payload: dict = {"result": result}
        if artifact_id:
            result_payload["artifact_id"] = artifact_id
        sql = (
            "UPDATE tool_call_attempts SET "
            "status = 'executed', result = CAST(:result AS jsonb)"
        )
        params: dict[str, Any] = {
            "call_id": call_id,
            "result": json.dumps(result_payload, cls=PGNativeJSONEncoder),
        }
        if message_id is not None:
            sql += ", message_id = CAST(:message_id AS uuid)"
            params["message_id"] = message_id
        sql += " WHERE call_id = :call_id"
        result_proxy = self._conn.execute(text(sql), params)
        return result_proxy.rowcount > 0

    def mark_failed(self, call_id: str, error: str) -> bool:
        """Flip ``proposed`` → ``failed`` with the exception text."""
        result = self._conn.execute(
            text(
                "UPDATE tool_call_attempts SET status = 'failed', error = :error "
                "WHERE call_id = :call_id"
            ),
            {"call_id": call_id, "error": error},
        )
        return result.rowcount > 0
