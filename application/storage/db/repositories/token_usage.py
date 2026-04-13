"""Repository for the ``token_usage`` table.

Covers every operation the legacy Mongo code performs on
``token_usage_collection`` / ``usage_collection``:

1. ``insert_one`` in usage.py (record per-call token counts)
2. ``aggregate`` in analytics/routes.py (time-bucketed totals)
3. ``aggregate`` in answer/routes/base.py (24h sum for rate limiting)
4. ``count_documents`` in answer/routes/base.py (24h request count)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Connection, text


class TokenUsageRepository:
    """Postgres-backed replacement for Mongo ``token_usage_collection``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(
        self,
        *,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        prompt_tokens: int = 0,
        generated_tokens: int = 0,
        timestamp: Optional[datetime] = None,
    ) -> None:
        self._conn.execute(
            text(
                """
                INSERT INTO token_usage (user_id, api_key, agent_id, prompt_tokens, generated_tokens, timestamp)
                VALUES (
                    :user_id, :api_key,
                    CAST(:agent_id AS uuid),
                    :prompt_tokens, :generated_tokens,
                    COALESCE(:timestamp, now())
                )
                """
            ),
            {
                "user_id": user_id,
                "api_key": api_key,
                "agent_id": agent_id,
                "prompt_tokens": prompt_tokens,
                "generated_tokens": generated_tokens,
                "timestamp": timestamp,
            },
        )

    def sum_tokens_in_range(
        self,
        *,
        start: datetime,
        end: datetime,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> int:
        """Total (prompt + generated) tokens in the given time range."""
        clauses = ["timestamp >= :start", "timestamp <= :end"]
        params: dict = {"start": start, "end": end}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if api_key is not None:
            clauses.append("api_key = :api_key")
            params["api_key"] = api_key
        where = " AND ".join(clauses)
        result = self._conn.execute(
            text(f"SELECT COALESCE(SUM(prompt_tokens + generated_tokens), 0) FROM token_usage WHERE {where}"),
            params,
        )
        return result.scalar()

    def count_in_range(
        self,
        *,
        start: datetime,
        end: datetime,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> int:
        """Count of token_usage rows in the given time range (for request limiting)."""
        clauses = ["timestamp >= :start", "timestamp <= :end"]
        params: dict = {"start": start, "end": end}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if api_key is not None:
            clauses.append("api_key = :api_key")
            params["api_key"] = api_key
        where = " AND ".join(clauses)
        result = self._conn.execute(
            text(f"SELECT COUNT(*) FROM token_usage WHERE {where}"),
            params,
        )
        return result.scalar()
