"""Repository for ``request_traces``: one stored execution trace per request."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder
from docsgpt.utils import strip_null_bytes

logger = logging.getLogger(__name__)

#: Columns a trace can be looked up by, mapped to their SQL type.
REF_FIELDS: Dict[str, str] = {
    "id": "uuid",
    "request_id": "text",
    "message_id": "uuid",
    "activity_id": "text",
    "workflow_run_id": "uuid",
}

_SUMMARY_COLUMNS = (
    "id, request_id, message_id, conversation_id, activity_id, workflow_run_id, "
    "user_id, agent_id, source, name, status, started_at, duration_ms, "
    "span_count, dropped_spans, summary, otel_trace_id"
)


def _dump_jsonb(value: Any) -> str:
    """Serialize ``value`` for a JSONB parameter, without NUL bytes Postgres rejects."""
    return json.dumps(strip_null_bytes(value), cls=PGNativeJSONEncoder)


def _uuid_or_none(value: Optional[str]) -> Optional[str]:
    """``value`` as a string when it is a UUID, else ``None`` (the column is typed)."""
    return str(value) if value and looks_like_uuid(str(value)) else None


def _started_at(record: Dict[str, Any]) -> datetime.datetime:
    started_ns = record.get("started_at_ns")
    if started_ns:
        return datetime.datetime.fromtimestamp(started_ns / 1e9, tz=datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc)


def _scope_clause(user_id: Optional[str], agent_id: Optional[str]) -> tuple[str, Dict[str, Any]]:
    """Owner scoping: an owned agent's traces, else the caller's own traces."""
    if agent_id:
        return "agent_id = CAST(:scope_agent AS uuid)", {"scope_agent": str(agent_id)}
    return "user_id = :scope_user", {"scope_user": user_id}


class RequestTracesRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, record: Dict[str, Any]) -> bool:
        """Insert one finished trace (the dict from ``Trace.to_record``).

        A foreign-key failure means the message was deleted before the trace
        flushed (e.g. the turn was superseded); the trace describes a turn the
        user discarded, so it is dropped rather than raised. The insert runs
        in a savepoint so that drop leaves the caller's transaction usable.

        Args:
            record: The trace record.

        Returns:
            True when the row was written.
        """
        params = {
            "id": record["id"],
            "request_id": record.get("request_id"),
            "message_id": _uuid_or_none(record.get("message_id")),
            "conversation_id": _uuid_or_none(record.get("conversation_id")),
            "activity_id": record.get("activity_id"),
            "workflow_run_id": _uuid_or_none(record.get("workflow_run_id")),
            "user_id": record.get("user_id"),
            "agent_id": _uuid_or_none(record.get("agent_id")),
            "source": record.get("source") or "unknown",
            "name": strip_null_bytes(record.get("name")),
            "status": record.get("status") or "ok",
            "started_at": _started_at(record),
            "duration_ms": int(record.get("duration_ms") or 0),
            "span_count": int(record.get("span_count") or 0),
            "dropped_spans": int(record.get("dropped_spans") or 0),
            "summary": _dump_jsonb(record.get("summary") or {}),
            "spans": _dump_jsonb(record.get("spans") or []),
            "otel_trace_id": record.get("otel_trace_id"),
        }
        statement = text(
            """
            INSERT INTO request_traces
                (id, request_id, message_id, conversation_id, activity_id,
                 workflow_run_id, user_id, agent_id, source, name, status,
                 started_at, duration_ms, span_count, dropped_spans, summary,
                 spans, otel_trace_id)
            VALUES
                (CAST(:id AS uuid), :request_id, CAST(:message_id AS uuid),
                 CAST(:conversation_id AS uuid), :activity_id,
                 CAST(:workflow_run_id AS uuid), :user_id, CAST(:agent_id AS uuid),
                 :source, :name, :status, :started_at, :duration_ms, :span_count,
                 :dropped_spans, CAST(:summary AS jsonb), CAST(:spans AS jsonb),
                 :otel_trace_id)
            ON CONFLICT (id) DO NOTHING
            """
        )
        try:
            with self._conn.begin_nested():
                result = self._conn.execute(statement, params)
        except IntegrityError as exc:
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if sqlstate != "23503":
                raise
            logger.info("Dropped trace %s: its message no longer exists", record["id"])
            return False
        return (result.rowcount or 0) > 0

    def list_by_ref(
        self,
        field: str,
        value: str,
        *,
        user_id: Optional[str],
        agent_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """Full traces matching ``field = value``, oldest first, owner-scoped.

        Args:
            field: One of :data:`REF_FIELDS`.
            value: The id to match.
            user_id: The caller; used when ``agent_id`` is not given.
            agent_id: An agent the caller owns; scopes to that agent's traces.
            limit: Maximum traces returned.

        Returns:
            Trace dicts including ``spans``; empty for an unknown field or id.
        """
        sql_type = REF_FIELDS.get(field)
        if sql_type is None or not value:
            return []
        if sql_type == "uuid" and not looks_like_uuid(str(value)):
            return []
        if not agent_id and not user_id:
            return []
        scope, scope_params = _scope_clause(user_id, agent_id)
        result = self._conn.execute(
            text(
                f"""
                SELECT {_SUMMARY_COLUMNS}, spans FROM request_traces
                WHERE {field} = CAST(:value AS {sql_type}) AND {scope}
                ORDER BY started_at
                LIMIT :limit
                """
            ),
            {"value": str(value), "limit": max(1, min(int(limit), 100)), **scope_params},
        )
        return [row_to_dict(row) for row in result.fetchall()]

    def summaries_for_refs(
        self,
        refs: Dict[str, Iterable[str]],
        *,
        user_id: Optional[str],
        agent_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, List[dict]]]:
        """Trace summaries (no spans) for a page of Logs rows.

        Args:
            refs: ``{field: [ids...]}`` for fields in :data:`REF_FIELDS`.
            user_id: The caller; used when ``agent_id`` is not given.
            agent_id: An agent the caller owns.

        Returns:
            ``{field: {id: [summary, ...]}}`` with summaries oldest first.
        """
        out: Dict[str, Dict[str, List[dict]]] = {}
        if not agent_id and not user_id:
            return out
        scope, scope_params = _scope_clause(user_id, agent_id)
        for field, values in refs.items():
            sql_type = REF_FIELDS.get(field)
            if sql_type is None:
                continue
            ids = sorted({str(v) for v in values if v})
            if sql_type == "uuid":
                ids = [v for v in ids if looks_like_uuid(v)]
            if not ids:
                continue
            result = self._conn.execute(
                text(
                    f"""
                    SELECT {_SUMMARY_COLUMNS} FROM request_traces
                    WHERE {field} = ANY(CAST(:ids AS {sql_type}[])) AND {scope}
                    ORDER BY started_at
                    """
                ),
                {"ids": ids, **scope_params},
            )
            for row in result.fetchall():
                data = row_to_dict(row)
                out.setdefault(field, {}).setdefault(str(data[field]), []).append(data)
        return out

    def purge_older_than(self, days: int) -> int:
        """Delete traces older than ``days`` (the retention window)."""
        result = self._conn.execute(
            text(
                "DELETE FROM request_traces "
                "WHERE created_at < NOW() - CAST(:days || ' days' AS interval)"
            ),
            {"days": str(max(1, days))},
        )
        return result.rowcount or 0
