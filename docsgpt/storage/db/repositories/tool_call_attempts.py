"""Repository for ``tool_call_attempts``; executor's proposed/executed/failed writes."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes


def _dump_jsonb(value: Any) -> str:
    """Serialize for a jsonb CAST, stripping NULs Postgres would reject."""
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


def _result_payload(result: Any, artifact_id: Optional[str], app_result: Optional[dict]) -> dict:
    """The ``result`` JSONB of an executed row."""
    payload: dict = {"result": result}
    if artifact_id:
        payload["artifact_id"] = artifact_id
    if app_result is not None:
        payload["app_result"] = app_result
    return payload


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
        message_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> bool:
        """Insert a ``proposed`` row before the tool executes.

        Returns True if a new row was created. ``ON CONFLICT DO NOTHING``
        guards against the LLM emitting a duplicate ``call_id``: the
        existing row stays put rather than a re-insert raising
        ``IntegrityError``.

        ``message_id`` / ``user_id`` / ``agent_id`` attribute the attempt
        from the start — headless runs and parse-failure rows never reach
        ``mark_executed``, and headless runs have no message at all.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO tool_call_attempts
                    (call_id, tool_id, tool_name, action_name, arguments,
                     message_id, user_id, agent_id, status)
                VALUES
                    (:call_id, CAST(:tool_id AS uuid), :tool_name,
                     :action_name, CAST(:arguments AS jsonb),
                     CAST(:message_id AS uuid), :user_id,
                     CAST(:agent_id AS uuid), 'proposed')
                ON CONFLICT (call_id) DO NOTHING
                """
            ),
            {
                "call_id": call_id,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "action_name": action_name,
                "arguments": _dump_jsonb(arguments if arguments is not None else {}),
                "message_id": message_id,
                "user_id": user_id,
                "agent_id": agent_id,
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
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        app_result: Optional[dict] = None,
    ) -> None:
        """Insert OR upgrade a row to ``executed`` — or ``confirmed`` when
        there is no ``message_id``, as in ``mark_executed``.

        Used as a fallback when ``record_proposed`` failed (DB outage)
        and the tool ran anyway — preserves the journal so the
        reconciler can still see the attempt. ``user_id`` / ``agent_id``
        attribute the synthesized row so it stays visible to per-user /
        per-agent analytics.

        The ``ON CONFLICT`` upgrade is guarded to a still-``proposed`` row
        owned by the same ``user_id``: ``call_id`` is the table-wide PK
        and LLMs reuse ids, so without it a colliding write could upgrade
        another request's (possibly another tenant's) row.
        """
        result_payload = _result_payload(result, artifact_id, app_result)
        status = "executed" if message_id is not None else "confirmed"
        self._conn.execute(
            text(
                """
                INSERT INTO tool_call_attempts
                    (call_id, tool_id, tool_name, action_name, arguments,
                     result, message_id, user_id, agent_id, status)
                VALUES
                    (:call_id, CAST(:tool_id AS uuid), :tool_name,
                     :action_name, CAST(:arguments AS jsonb),
                     CAST(:result AS jsonb), CAST(:message_id AS uuid),
                     :user_id, CAST(:agent_id AS uuid), :status)
                ON CONFLICT (call_id) DO UPDATE
                   SET status     = :status,
                       result     = EXCLUDED.result,
                       message_id = COALESCE(EXCLUDED.message_id, tool_call_attempts.message_id)
                 WHERE tool_call_attempts.status = 'proposed'
                   AND tool_call_attempts.user_id IS NOT DISTINCT FROM EXCLUDED.user_id
                """
            ),
            {
                "call_id": call_id,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "action_name": action_name,
                "arguments": _dump_jsonb(arguments if arguments is not None else {}),
                "result": _dump_jsonb(result_payload),
                "message_id": message_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "status": status,
            },
        )

    def mark_executed(
        self,
        call_id: str,
        result: Any,
        *,
        message_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
        user_id: Optional[str] = None,
        app_result: Optional[dict] = None,
    ) -> bool:
        """Flip ``proposed`` → ``executed``, or straight to ``confirmed``
        when there is no ``message_id`` (a ``save_conversation=False``
        request reserves no message, so no finalize will confirm it).

        ``artifact_id`` (when present) is stored alongside ``result`` in
        the JSONB as audit data — the reconciler reads it for diagnostic
        alerts when escalating stuck rows to ``failed``. ``app_result``
        (an MCP App view's result) goes there too, for ``get_app_result``.

        Guarded to a still-``proposed`` row (and, when ``user_id`` is
        given, to one owned by that user): ``call_id`` is the table-wide
        PK and LLMs reuse ids, so an unguarded update could flip another
        request's already-terminal — or another tenant's — row.
        """
        result_payload = _result_payload(result, artifact_id, app_result)
        status = "executed" if message_id is not None else "confirmed"
        sql = (
            "UPDATE tool_call_attempts SET "
            "status = :status, result = CAST(:result AS jsonb)"
        )
        params: dict[str, Any] = {
            "call_id": call_id,
            "status": status,
            "result": _dump_jsonb(result_payload),
        }
        if message_id is not None:
            sql += ", message_id = CAST(:message_id AS uuid)"
            params["message_id"] = message_id
        sql += " WHERE call_id = :call_id AND status = 'proposed'"
        if user_id is not None:
            sql += " AND user_id IS NOT DISTINCT FROM :user_id"
            params["user_id"] = user_id
        result_proxy = self._conn.execute(text(sql), params)
        return result_proxy.rowcount > 0

    def get_app_result(self, message_id: str, call_id: str) -> Optional[dict]:
        """The MCP App view result journaled for a call of a message, or None.

        Args:
            message_id: The message the call belongs to.
            call_id: The call's id as the chat knows it (not the journal key).

        Returns:
            The ``CallToolResult`` the view was handed live.
        """
        row = self._conn.execute(
            text(
                "SELECT result -> 'app_result' AS app_result FROM tool_call_attempts "
                "WHERE call_id = :key AND message_id = CAST(:mid AS uuid)"
            ),
            {"key": f"{message_id}:{call_id}", "mid": message_id},
        ).fetchone()
        value = row._mapping["app_result"] if row is not None else None
        return value if isinstance(value, dict) else None

    def attach_message(self, call_ids: list[str], message_id: str) -> int:
        """Point journal rows written before their turn's message existed at that message.

        A continuation turn journals its calls keyed by the id its message
        will get, with ``message_id`` empty (the foreign key can't name a row
        that doesn't exist yet); once the message is written, they are linked.

        Args:
            call_ids: The rows' journal keys (``<message_id>:<call_id>``).
            message_id: The message, now written.

        Returns:
            Rows linked.
        """
        if not call_ids:
            return 0
        result = self._conn.execute(
            text(
                "UPDATE tool_call_attempts SET message_id = CAST(:mid AS uuid), updated_at = now() "
                "WHERE call_id = ANY(:keys) AND message_id IS NULL"
            ),
            {"mid": message_id, "keys": list(call_ids)},
        )
        return result.rowcount or 0

    def mark_failed(
        self, call_id: str, error: str, *, user_id: Optional[str] = None
    ) -> bool:
        """Flip ``proposed`` → ``failed`` with the exception text.

        The status guard matters: ``call_id`` is the table-wide PK and
        LLMs have been observed reusing ids ("call_0"-style). Without it,
        a duplicate id hitting an error path would flip an already
        ``executed``/``confirmed`` row — possibly another request's —
        to ``failed``, and nothing ever repairs that. When ``user_id`` is
        given the update is additionally scoped to that owner, so a
        colliding id from another tenant can't fail this row.
        """
        sql = (
            "UPDATE tool_call_attempts SET status = 'failed', error = :error "
            "WHERE call_id = :call_id AND status = 'proposed'"
        )
        params: dict[str, Any] = {
            "call_id": call_id,
            "error": strip_null_bytes(error),
        }
        if user_id is not None:
            sql += " AND user_id IS NOT DISTINCT FROM :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        return result.rowcount > 0
