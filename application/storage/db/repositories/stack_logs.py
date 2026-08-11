"""Repository for the ``stack_logs`` table.

Covers the single operation the legacy Mongo code performs:

1. ``insert_one`` in logging.py ``_log_to_mongodb`` — append-only debug/error
   activity log. The Mongo collection is ``stack_logs``; the Mongo variable
   inside ``_log_to_mongodb`` is misleadingly named ``user_logs_collection``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from application.storage.db.redaction import redact_secrets
from application.storage.db.serialization import PGNativeJSONEncoder
from application.utils import strip_null_bytes

from sqlalchemy import Connection, text

# Longest string kept inside ``stacks``. The scalar columns are truncated
# by the caller, but stacks used to go in whole — one uncapped tool
# result (634k tokens, 07-17) rode into the activity log through here.
_STACKS_STRING_MAX_LEN = 10000


def _bound_strings(value):
    """Recursively truncate strings in ``value`` to ``_STACKS_STRING_MAX_LEN``."""
    if isinstance(value, str):
        if len(value) <= _STACKS_STRING_MAX_LEN:
            return value
        return value[:_STACKS_STRING_MAX_LEN] + "...[truncated]"
    if isinstance(value, dict):
        return {k: _bound_strings(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bound_strings(item) for item in value]
    return value


class StackLogsRepository:
    """Postgres-backed replacement for Mongo ``stack_logs`` collection."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        activity_id: str,
        endpoint: Optional[str] = None,
        level: Optional[str] = None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        query: Optional[str] = None,
        stacks: Optional[list] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        # ``agent_id`` is a UUID column. Parse it with ``uuid.UUID`` and coerce
        # anything that isn't a valid UUID (e.g. a 24-hex legacy Mongo ObjectId)
        # to NULL so a stray/legacy id never reaches ``CAST(... AS uuid)`` and
        # breaks the activity-log write.
        agent_id_uuid: Optional[str] = None
        if agent_id:
            try:
                agent_id_uuid = str(uuid.UUID(str(agent_id)))
            except (ValueError, AttributeError, TypeError):
                agent_id_uuid = None
        self._conn.execute(
            text(
                """
                INSERT INTO stack_logs (activity_id, endpoint, level, user_id, api_key, agent_id, query, stacks, timestamp)
                VALUES (
                    :activity_id, :endpoint, :level, :user_id, :api_key,
                    CAST(:agent_id AS uuid), :query,
                    CAST(:stacks AS jsonb),
                    COALESCE(:timestamp, now())
                )
                """
            ),
            {
                "activity_id": activity_id,
                "endpoint": strip_null_bytes(endpoint),
                "level": strip_null_bytes(level),
                "user_id": strip_null_bytes(user_id),
                "api_key": strip_null_bytes(api_key),
                "agent_id": agent_id_uuid,
                "query": strip_null_bytes(query),
                "stacks": json.dumps(
                    redact_secrets(
                        _bound_strings(strip_null_bytes(stacks or []))
                    ),
                    cls=PGNativeJSONEncoder,
                ),
                "timestamp": timestamp,
            },
        )

    def reassign_api_key(self, *, old_key: str, new_key: str) -> int:
        """Re-point historical rows from ``old_key`` to ``new_key``.

        Since migration 0026 ``stack_logs`` has an ``agent_id`` column and the
        analytics ``webhook_where`` / ``system_where`` clauses match
        ``agent_id`` first with ``api_key`` as a fallback, so most rows already
        survive a key rotation via ``agent_id``. This rewrite still runs to keep
        the ``api_key`` column consistent and to re-attach any rows whose
        ``agent_id`` is NULL (e.g. a log written without agent context).

        Matched by ``api_key`` only — deliberately NOT scoped by ``user_id``:
        ``agents.key`` is globally unique, so a key maps to exactly one agent,
        and rows are stamped with the *caller's* user_id (which is not the
        owner for webhook / external-api-key traffic). Scoping by owner would
        skip precisely the rows this rewrite exists to preserve.
        Returns the number of rows updated.
        """
        if not old_key or not new_key:
            return 0
        result = self._conn.execute(
            text("UPDATE stack_logs SET api_key = :new_key WHERE api_key = :old_key"),
            {"old_key": old_key, "new_key": new_key},
        )
        return result.rowcount
