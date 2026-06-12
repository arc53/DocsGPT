"""Repository for the ``user_logs`` table (write-only).

The single production write site is the per-stream log entry in
answer/routes/base.py. Reads go through the unified timeline query in
api/user/analytics/routes.py (GetUserLogs).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.serialization import PGNativeJSONEncoder


class UserLogsRepository:
    """Postgres-backed replacement for Mongo ``user_logs_collection``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        user_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        data: Optional[dict] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        self._conn.execute(
            text(
                """
                INSERT INTO user_logs (user_id, endpoint, data, timestamp)
                VALUES (:user_id, :endpoint, CAST(:data AS jsonb), COALESCE(:timestamp, now()))
                """
            ),
            {
                "user_id": user_id,
                "endpoint": endpoint,
                "data": json.dumps(data, cls=PGNativeJSONEncoder) if data is not None else None,
                "timestamp": timestamp,
            },
        )

    # NOTE: reads live in the unified timeline query in
    # api/user/analytics/routes.py (GetUserLogs) — extend that rather
    # than re-adding per-table readers here.
