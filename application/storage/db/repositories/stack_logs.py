"""Repository for the ``stack_logs`` table.

Covers the single operation the legacy Mongo code performs:

1. ``insert_one`` in logging.py ``_log_to_mongodb`` — append-only debug/error
   activity log. The Mongo collection is ``stack_logs``; the Mongo variable
   inside ``_log_to_mongodb`` is misleadingly named ``user_logs_collection``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from application.storage.db.serialization import PGNativeJSONEncoder

from sqlalchemy import Connection, text


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
        query: Optional[str] = None,
        stacks: Optional[list] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        self._conn.execute(
            text(
                """
                INSERT INTO stack_logs (activity_id, endpoint, level, user_id, api_key, query, stacks, timestamp)
                VALUES (
                    :activity_id, :endpoint, :level, :user_id, :api_key, :query,
                    CAST(:stacks AS jsonb),
                    COALESCE(:timestamp, now())
                )
                """
            ),
            {
                "activity_id": activity_id,
                "endpoint": endpoint,
                "level": level,
                "user_id": user_id,
                "api_key": api_key,
                "query": query,
                "stacks": json.dumps(stacks or [], cls=PGNativeJSONEncoder),
                "timestamp": timestamp,
            },
        )
