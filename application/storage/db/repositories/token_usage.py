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
        source: str = "agent_stream",
        request_id: Optional[str] = None,
        model_id: Optional[str] = None,
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
                INSERT INTO token_usage (
                    user_id, api_key, agent_id,
                    prompt_tokens, generated_tokens,
                    source, request_id, model_id, timestamp
                )
                VALUES (
                    :user_id, :api_key,
                    CAST(:agent_id AS uuid),
                    :prompt_tokens, :generated_tokens,
                    :source, :request_id, :model_id, COALESCE(:timestamp, now())
                )
                """
            ),
            {
                "user_id": user_id,
                "api_key": api_key,
                "agent_id": agent_id_uuid,
                "prompt_tokens": prompt_tokens,
                "generated_tokens": generated_tokens,
                "source": source,
                "request_id": request_id,
                "model_id": model_id,
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

    # Token usage written outside a user-initiated request (conversation
    # title generation, history compression, RAG question condensing,
    # provider fallback). Mirrors the exclusion list in ``count_in_range``.
    SIDE_CHANNEL_SOURCES = ("title", "compression", "rag_condense", "fallback")

    # Run-level roll-ups that duplicate per-call rows. The scheduler worker
    # inserts one ``source='schedule'`` row summing a run's tokens, but the
    # run's individual LLM calls were already persisted as ``agent_stream``
    # rows by the usage decorators — counting both doubles scheduled spend.
    # The rollup is never used as a fallback: if a per-call insert failed
    # (logged in usage.py), that call's tokens go uncounted, the same loss
    # mode as any other traffic whose insert fails.
    ROLLUP_SOURCES = ("schedule",)

    # Allowed ``group_by`` values → the SQL expression producing the
    # group key. ``agent`` resolves to the agent's display name so the
    # dashboard never has to map UUIDs client-side.
    _GROUP_KEY_EXPRS = {
        "model": "COALESCE(tu.model_id, 'unknown')",
        "agent": "COALESCE(a.name, 'No agent')",
        "source": "COALESCE(tu.source, 'agent_stream')",
    }

    def bucketed_totals(
        self,
        *,
        bucket_unit: str,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        timestamp_gte: Optional[datetime] = None,
        timestamp_lt: Optional[datetime] = None,
        group_by: Optional[str] = None,
        include_side_channel: bool = True,
    ) -> list[dict]:
        """Sum ``prompt_tokens`` / ``generated_tokens`` bucketed by time.

        Replacement for the legacy Mongo ``$dateToString`` aggregation
        used by the analytics dashboard. The ``bucket`` format string
        mirrors Mongo's output so the route layer doesn't reshape:
        ``"YYYY-MM-DD HH:MM:00"`` (minute), ``"YYYY-MM-DD HH:00"``
        (hour), ``"YYYY-MM-DD"`` (day). Rows are ordered by bucket ASC.

        ``group_by`` (``"model"`` / ``"agent"`` / ``"source"``) adds a
        second grouping dimension; each returned row then carries a
        ``group_key``. ``include_side_channel=False`` drops rows whose
        ``source`` is a side-channel call (title generation etc.).
        """
        formats = {
            "minute": "YYYY-MM-DD HH24:MI:00",
            "hour": "YYYY-MM-DD HH24:00",
            "day": "YYYY-MM-DD",
        }
        if bucket_unit not in formats:
            raise ValueError(f"unsupported bucket_unit: {bucket_unit!r}")
        if group_by is not None and group_by not in self._GROUP_KEY_EXPRS:
            raise ValueError(f"unsupported group_by: {group_by!r}")
        fmt = formats[bucket_unit]

        clauses: list[str] = []
        params: dict = {"fmt": fmt}
        if user_id is not None:
            clauses.append("tu.user_id = :user_id")
            params["user_id"] = user_id
        # Rows stamp ``api_key`` (external traffic) or ``agent_id``
        # (owner chats / headless runs), so a per-agent filter must
        # match either shape.
        agent_clauses: list[str] = []
        if api_key is not None:
            agent_clauses.append("tu.api_key = :api_key")
            params["api_key"] = api_key
        if agent_id is not None:
            agent_clauses.append("tu.agent_id = CAST(:agent_id AS uuid)")
            params["agent_id"] = agent_id
        if agent_clauses:
            clauses.append(f"({' OR '.join(agent_clauses)})")
        if timestamp_gte is not None:
            clauses.append("tu.timestamp >= :timestamp_gte")
            params["timestamp_gte"] = timestamp_gte
        if timestamp_lt is not None:
            clauses.append("tu.timestamp < :timestamp_lt")
            params["timestamp_lt"] = timestamp_lt
        excluded_sources = list(self.ROLLUP_SOURCES)
        if not include_side_channel:
            excluded_sources.extend(self.SIDE_CHANNEL_SOURCES)
        placeholders = []
        for i, src in enumerate(excluded_sources):
            key = f"excl_src_{i}"
            placeholders.append(f":{key}")
            params[key] = src
        clauses.append(
            f"COALESCE(tu.source, 'agent_stream') NOT IN ({', '.join(placeholders)})"
        )
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        group_select = ""
        group_clause = ""
        join = ""
        if group_by is not None:
            group_select = f", {self._GROUP_KEY_EXPRS[group_by]} AS group_key"
            group_clause = ", group_key"
            if group_by == "agent":
                join = "LEFT JOIN agents a ON a.id = tu.agent_id"
        result = self._conn.execute(
            text(
                f"""
                SELECT to_char(tu.timestamp AT TIME ZONE 'UTC', :fmt) AS bucket,
                       COALESCE(SUM(tu.prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(tu.generated_tokens), 0) AS generated_tokens
                       {group_select}
                FROM token_usage tu
                {join}
                {where}
                GROUP BY bucket{group_clause}
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
                **(
                    {"group_key": row._mapping["group_key"]}
                    if group_by is not None
                    else {}
                ),
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
        """Count user-initiated requests in the given time range.

        A request = one ``agent_stream`` invocation. Multi-tool agent
        runs produce multiple rows (one per LLM call) tagged with the
        same ``request_id``; we DISTINCT on that to count the request
        once. Pre-migration rows have ``request_id=NULL`` and are
        counted one-per-row via the second branch (back-compat).
        Side-channel sources (``title`` / ``compression`` /
        ``rag_condense`` / ``fallback``) are excluded — they aren't
        user-initiated and shouldn't tick the request limit.
        """
        clauses = [
            "timestamp >= :start",
            "timestamp <= :end",
            "source = 'agent_stream'",
        ]
        params: dict = {"start": start, "end": end}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if api_key is not None:
            clauses.append("api_key = :api_key")
            params["api_key"] = api_key
        where = " AND ".join(clauses)
        result = self._conn.execute(
            text(
                f"""
                SELECT
                    COUNT(DISTINCT request_id) FILTER (WHERE request_id IS NOT NULL)
                    + COUNT(*) FILTER (WHERE request_id IS NULL)
                FROM token_usage
                WHERE {where}
                """
            ),
            params,
        )
        return result.scalar()
