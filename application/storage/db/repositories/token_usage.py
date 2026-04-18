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
        # Attribution guard: the ``token_usage_attribution_chk`` CHECK
        # constraint requires at least one of ``user_id`` / ``api_key``
        # to be non-null. Raise here for a clear error rather than
        # relying on the DB to reject the row.
        if not user_id and not api_key:
            raise ValueError("token_usage insert requires user_id or api_key")

        # ``agent_id`` is a UUID column. Legacy callers occasionally pass
        # a Mongo ObjectId string (24 hex chars) — those would make
        # psycopg raise at CAST time. Coerce anything that isn't shaped
        # like a UUID (36 chars with hyphens) to NULL so a stray legacy
        # id never breaks token accounting.
        agent_id_uuid: Optional[str] = None
        if agent_id:
            s = str(agent_id)
            if len(s) == 36 and "-" in s:
                agent_id_uuid = s

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
                "agent_id": agent_id_uuid,
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

    def bucketed_totals(
        self,
        *,
        bucket_unit: str,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        timestamp_gte: Optional[datetime] = None,
        timestamp_lt: Optional[datetime] = None,
    ) -> list[dict]:
        """Sum ``prompt_tokens`` / ``generated_tokens`` bucketed by time.

        Replacement for the legacy Mongo ``$dateToString`` aggregation
        used by the analytics dashboard. The ``bucket`` format string
        mirrors Mongo's output so the route layer doesn't reshape:
        ``"YYYY-MM-DD HH:MM:00"`` (minute), ``"YYYY-MM-DD HH:00"``
        (hour), ``"YYYY-MM-DD"`` (day). Rows are ordered by bucket ASC.
        """
        formats = {
            "minute": "YYYY-MM-DD HH24:MI:00",
            "hour": "YYYY-MM-DD HH24:00",
            "day": "YYYY-MM-DD",
        }
        if bucket_unit not in formats:
            raise ValueError(f"unsupported bucket_unit: {bucket_unit!r}")
        fmt = formats[bucket_unit]

        clauses: list[str] = []
        params: dict = {"fmt": fmt}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if api_key is not None:
            clauses.append("api_key = :api_key")
            params["api_key"] = api_key
        if agent_id is not None:
            clauses.append("agent_id = CAST(:agent_id AS uuid)")
            params["agent_id"] = agent_id
        if timestamp_gte is not None:
            clauses.append("timestamp >= :timestamp_gte")
            params["timestamp_gte"] = timestamp_gte
        if timestamp_lt is not None:
            clauses.append("timestamp < :timestamp_lt")
            params["timestamp_lt"] = timestamp_lt
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        result = self._conn.execute(
            text(
                f"""
                SELECT to_char(timestamp AT TIME ZONE 'UTC', :fmt) AS bucket,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(generated_tokens), 0) AS generated_tokens
                FROM token_usage
                {where}
                GROUP BY bucket
                ORDER BY bucket ASC
                """
            ),
            params,
        )
        return [
            {
                "bucket": row._mapping["bucket"],
                "prompt_tokens": int(row._mapping["prompt_tokens"]),
                "generated_tokens": int(row._mapping["generated_tokens"]),
            }
            for row in result.fetchall()
        ]

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
