"""Repository for the ``user_logs`` table.

Covers every operation the legacy Mongo code performs on
``user_logs_collection``:

1. ``insert_one`` in logging.py (per-request activity log via
   ``_log_to_mongodb`` — note: the *Mongo* variable is confusingly named
   ``user_logs_collection`` but points at the ``user_logs`` Mongo
   collection, not ``stack_logs``)
2. ``insert_one`` in answer/routes/base.py (per-stream log entry)
3. ``find`` with sort/skip/limit in analytics/routes.py (paginated log list)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


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
                "data": json.dumps(data, default=str) if data is not None else None,
                "timestamp": timestamp,
            },
        )

    def list_paginated(
        self,
        *,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict], bool]:
        """Return ``(rows, has_more)`` for the requested page.

        Mirrors the Mongo ``find(query).sort().skip().limit(page_size+1)``
        pattern used in analytics/routes.py.
        """
        clauses: list[str] = []
        params: dict = {"limit": page_size + 1, "offset": (page - 1) * page_size}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if api_key is not None:
            clauses.append("data->>'api_key' = :api_key")
            params["api_key"] = api_key
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        result = self._conn.execute(
            text(
                f"SELECT * FROM user_logs {where} ORDER BY timestamp DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = [row_to_dict(r) for r in result.fetchall()]
        has_more = len(rows) > page_size
        return rows[:page_size], has_more

    def find_by_api_key(
        self,
        api_key: str,
        *,
        timestamp_gte: Optional[datetime] = None,
        timestamp_lt: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """Return user_logs rows whose ``data->>'api_key'`` matches ``api_key``.

        Replacement for the legacy Mongo filter by top-level ``api_key``;
        on the PG side the per-request payload lives in ``data`` JSONB,
        so the filter reaches in via ``data->>'api_key'``. Rows are
        ordered by ``timestamp DESC`` to match the Mongo sort.
        """
        clauses = ["data->>'api_key' = :api_key"]
        params: dict = {"api_key": api_key}
        if timestamp_gte is not None:
            clauses.append("timestamp >= :timestamp_gte")
            params["timestamp_gte"] = timestamp_gte
        if timestamp_lt is not None:
            clauses.append("timestamp < :timestamp_lt")
            params["timestamp_lt"] = timestamp_lt
        where = " AND ".join(clauses)
        sql = f"SELECT * FROM user_logs WHERE {where} ORDER BY timestamp DESC"
        if limit is not None:
            sql += " LIMIT :limit"
            params["limit"] = limit
        result = self._conn.execute(text(sql), params)
        return [row_to_dict(r) for r in result.fetchall()]
