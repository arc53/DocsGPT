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
from typing import Any, Iterable, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid

#: Usage buckets: every row, rows through an agent (a key or an agent id), rows with neither.
USAGE_BUCKETS = ("all", "agent", "direct")

#: The row filter of each bucket (``usage_totals``).
_BUCKET_FILTERS = {
    "all": "TRUE",
    "agent": "(api_key IS NOT NULL OR agent_id IS NOT NULL)",
    "direct": "(api_key IS NULL AND agent_id IS NULL)",
}

#: Run kinds a team's report counts as chats; every other kind (and none) is a run without a person.
_CHAT_KINDS = ("chat", "drafter")


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
        cached_tokens: Optional[int] = None,
        cache_write_tokens: Optional[int] = None,
        cost: float = 0.0,
        duration_ms: Optional[int] = None,
        ttft_ms: Optional[int] = None,
        team_id: Optional[str] = None,
        run_kind: Optional[str] = None,
    ) -> None:
        """Record one model call.

        Args:
            user_id: Who pays for it; a person.
            api_key: The agent key it came through.
            agent_id: The agent it ran for; a value not shaped like a UUID is stored as NULL.
            prompt_tokens: Input tokens.
            generated_tokens: Output tokens.
            source: ``agent_stream`` or a side-channel source.
            request_id: The run's request id.
            model_id: The canonical model id.
            timestamp: When; now by default.
            cached_tokens: Prompt-cache reads, when the provider reported them.
            cache_write_tokens: Prompt-cache writes, when reported.
            cost: USD cost.
            duration_ms: Time waiting on the provider.
            ttft_ms: Time to the first streamed chunk.
            team_id: The team workspace it was made in; None (or a value not shaped like a UUID) is Personal.
            run_kind: What kind of run it was part of (``docsgpt.quotas.payer.RUN_KINDS``).

        Raises:
            ValueError: Neither ``user_id`` nor ``api_key`` is given.
        """
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
                    cached_tokens, cache_write_tokens, cost,
                    duration_ms, ttft_ms,
                    source, request_id, model_id, timestamp,
                    team_id, run_kind
                )
                VALUES (
                    :user_id, :api_key,
                    CAST(:agent_id AS uuid),
                    :prompt_tokens, :generated_tokens,
                    :cached_tokens, :cache_write_tokens, :cost,
                    :duration_ms, :ttft_ms,
                    :source, :request_id, :model_id, COALESCE(:timestamp, now()),
                    CAST(:team_id AS uuid), :run_kind
                )
                """
            ),
            {
                "user_id": user_id,
                "api_key": api_key,
                "agent_id": agent_id_uuid,
                "prompt_tokens": prompt_tokens,
                "generated_tokens": generated_tokens,
                "cached_tokens": cached_tokens,
                "cache_write_tokens": cache_write_tokens,
                "cost": cost,
                "duration_ms": duration_ms,
                "ttft_ms": ttft_ms,
                "source": source,
                "request_id": request_id,
                "model_id": model_id,
                "timestamp": timestamp,
                "team_id": str(team_id) if team_id and looks_like_uuid(str(team_id)) else None,
                "run_kind": run_kind,
            },
        )

    def reassign_api_key(self, *, old_key: str, new_key: str) -> int:
        """Re-point historical rows from ``old_key`` to ``new_key``.

        Called when an agent's key is rotated. Although per-agent analytics
        also match on ``agent_id``, the 24h rate-limit window
        (``sum_tokens_in_range`` / ``count_in_range``) and any legacy rows with
        a NULL ``agent_id`` are keyed by the api-key string only. Rewriting the
        key here preserves the running rate-limit window across a rotation (so
        rotating cannot be used to reset it) and keeps legacy rows attributed.
        Returns the number of rows updated.
        """
        if not old_key or not new_key:
            return 0
        result = self._conn.execute(
            text("UPDATE token_usage SET api_key = :new_key WHERE api_key = :old_key"),
            {"old_key": old_key, "new_key": new_key},
        )
        return result.rowcount

    @staticmethod
    def _agent_clause(api_key: Optional[str], agent_id: Optional[str], params: dict) -> Optional[str]:
        """The filter for one agent's rows: through its key, or stamped with its id.

        Chats and outside traffic stamp the key; keyless agents and workflow
        steps carry only the id. Adds the bound values to ``params``.

        Args:
            api_key: The agent's key, or None.
            agent_id: The agent's id (a UUID), or None.
            params: The query's bind parameters, extended in place.

        Returns:
            The SQL condition, or None when neither is given.
        """
        conditions = []
        if api_key is not None:
            conditions.append("api_key = :api_key")
            params["api_key"] = api_key
        if agent_id is not None:
            conditions.append("agent_id = CAST(:agent_id AS uuid)")
            params["agent_id"] = agent_id
        if not conditions:
            return None
        return f"({' OR '.join(conditions)})"

    def sum_tokens_in_range(
        self,
        *,
        start: datetime,
        end: datetime,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> int:
        """Total (prompt + generated) tokens in the given time range.

        Run-level rollup rows (``ROLLUP_SOURCES``) are excluded: their tokens
        are already counted on the run's per-call rows. ``api_key`` and
        ``agent_id`` together match a row carrying either (one agent, however
        reached; see :meth:`_agent_clause`).
        """
        clauses = ["timestamp >= :start", "timestamp <= :end", "source <> ALL(:rollup_sources)"]
        params: dict = {"start": start, "end": end, "rollup_sources": list(self.ROLLUP_SOURCES)}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        agent_clause = self._agent_clause(api_key, agent_id, params)
        if agent_clause:
            clauses.append(agent_clause)
        where = " AND ".join(clauses)
        result = self._conn.execute(
            text(f"SELECT COALESCE(SUM(prompt_tokens + generated_tokens), 0) FROM token_usage WHERE {where}"),
            params,
        )
        return result.scalar()

    def usage_totals(self, *, user_id: str, start: datetime, bucket: str = "all") -> tuple[int, float]:
        """Return ``(tokens, cost_usd)`` a user has consumed since ``start``.

        Args:
            user_id: The billable user (auth ``sub``).
            start: Inclusive window start.
            bucket: ``all``, ``agent`` (rows carrying an agent key or an agent
                id) or ``direct`` (rows with neither).

        Rollup rows are excluded; side-channel calls count, they are real spend.
        """
        clauses = ["user_id = :user_id", "timestamp >= :start", "source <> ALL(:rollup_sources)"]
        # Keyless agents and workflow nodes carry an agent id without a key.
        if bucket == "direct":
            clauses.append("api_key IS NULL AND agent_id IS NULL")
        elif bucket == "agent":
            clauses.append("(api_key IS NOT NULL OR agent_id IS NOT NULL)")
        elif bucket != "all":
            raise ValueError(f"unknown usage bucket: {bucket!r}")
        row = self._conn.execute(
            text(
                "SELECT COALESCE(SUM(prompt_tokens + generated_tokens), 0), COALESCE(SUM(cost), 0) "
                f"FROM token_usage WHERE {' AND '.join(clauses)}"
            ),
            {"user_id": user_id, "start": start, "rollup_sources": list(self.ROLLUP_SOURCES)},
        ).one()
        return int(row[0]), float(row[1])

    def usage_totals_for_buckets(
        self, user_id: str, start: datetime, buckets: Iterable[str] = ("all",)
    ) -> dict[str, tuple[int, float]]:
        """Return ``(tokens, cost_usd)`` a user has consumed since ``start`` in each bucket, in one query.

        Args:
            user_id: The billable user.
            start: Inclusive window start.
            buckets: Any of ``all``, ``agent`` and ``direct`` (see :meth:`usage_totals`).

        Returns:
            Bucket -> ``(tokens, cost_usd)``; rollup rows are excluded.

        Raises:
            ValueError: An unknown bucket.
        """
        wanted = list(dict.fromkeys(buckets))
        unknown = [bucket for bucket in wanted if bucket not in _BUCKET_FILTERS]
        if unknown:
            raise ValueError(f"unknown usage bucket: {unknown[0]!r}")
        if not wanted:
            return {}
        # The filters are fixed SQL keyed by bucket name; nothing the caller passes reaches the text.
        columns = ", ".join(
            f"COALESCE(SUM(prompt_tokens + generated_tokens) FILTER (WHERE {_BUCKET_FILTERS[b]}), 0), "
            f"COALESCE(SUM(cost) FILTER (WHERE {_BUCKET_FILTERS[b]}), 0)"
            for b in wanted
        )
        row = self._conn.execute(
            text(
                f"SELECT {columns} FROM token_usage "
                "WHERE user_id = :user_id AND timestamp >= :start AND source <> ALL(:rollup_sources)"
            ),
            {"user_id": user_id, "start": start, "rollup_sources": list(self.ROLLUP_SOURCES)},
        ).one()
        return {bucket: (int(row[2 * i]), float(row[2 * i + 1])) for i, bucket in enumerate(wanted)}

    def usage_by_kind(self, user_id: str, start: datetime) -> dict[Optional[str], tuple[int, float]]:
        """Return ``(tokens, cost_usd)`` a user has consumed since ``start``, by run kind.

        Args:
            user_id: The billable user.
            start: Inclusive window start.

        Returns:
            Run kind -> ``(tokens, cost_usd)``; rows written without a kind are under None. Rollup rows
            are excluded; a kind with no rows is absent.
        """
        result = self._conn.execute(
            text(
                "SELECT run_kind, COALESCE(SUM(prompt_tokens + generated_tokens), 0), COALESCE(SUM(cost), 0) "
                "FROM token_usage WHERE user_id = :user_id AND timestamp >= :start "
                "AND source <> ALL(:rollup_sources) GROUP BY run_kind"
            ),
            {"user_id": user_id, "start": start, "rollup_sources": list(self.ROLLUP_SOURCES)},
        )
        return {row[0]: (int(row[1]), float(row[2])) for row in result.fetchall()}

    def team_usage(self, team_id: str, start: datetime, end: datetime, *, limit: int = 200) -> dict[str, Any]:
        """Everything spent in a team workspace in ``[start, end)``, for its usage report.

        Only rows stamped with the team count: Personal rows and another
        team's never do, wherever the person or the agent is now. A call that
        billed nobody (a key's row with no person) counts in the totals but
        names no person.

        Args:
            team_id: The team.
            start: Inclusive window start.
            end: Exclusive window end.
            limit: The most people and agents listed, by cost then tokens.

        Returns:
            ``{"totals": {tokens, cost, people}, "split": {"chats": {tokens, cost}, "runs": {tokens, cost}},
            "by_person": [{user_id, tokens, cost}], "by_agent": [{agent_id, tokens, cost, requests, people}]}``.
            Chats are the ``chat`` and ``drafter`` kinds; runs are every other kind and rows with none.
            ``requests`` counts an agent's distinct requests as the agent limit does.
        """
        if not team_id or not looks_like_uuid(str(team_id)):
            return {
                "totals": {"tokens": 0, "cost": 0.0, "people": 0},
                "split": {"chats": {"tokens": 0, "cost": 0.0}, "runs": {"tokens": 0, "cost": 0.0}},
                "by_person": [],
                "by_agent": [],
            }
        params = {
            "team_id": str(team_id),
            "start": start,
            "end": end,
            "rollup_sources": list(self.ROLLUP_SOURCES),
            "chat_kinds": list(_CHAT_KINDS),
            "limit": int(limit),
        }
        where = (
            "team_id = CAST(:team_id AS uuid) AND timestamp >= :start AND timestamp < :end "
            "AND source <> ALL(:rollup_sources)"
        )
        tokens = "prompt_tokens + generated_tokens"
        is_chat = "run_kind = ANY(:chat_kinds)"
        totals = self._conn.execute(
            text(
                f"""
                SELECT COALESCE(SUM({tokens}), 0), COALESCE(SUM(cost), 0), COUNT(DISTINCT user_id),
                       COALESCE(SUM({tokens}) FILTER (WHERE {is_chat}), 0),
                       COALESCE(SUM(cost) FILTER (WHERE {is_chat}), 0),
                       COALESCE(SUM({tokens}) FILTER (WHERE run_kind IS NULL OR NOT {is_chat}), 0),
                       COALESCE(SUM(cost) FILTER (WHERE run_kind IS NULL OR NOT {is_chat}), 0)
                FROM token_usage WHERE {where}
                """
            ),
            params,
        ).one()
        people = self._conn.execute(
            text(
                f"""
                SELECT user_id, COALESCE(SUM({tokens}), 0) AS tokens, COALESCE(SUM(cost), 0) AS cost
                FROM token_usage WHERE {where} AND user_id IS NOT NULL
                GROUP BY user_id ORDER BY cost DESC, tokens DESC, user_id LIMIT :limit
                """
            ),
            params,
        ).fetchall()
        agents = self._conn.execute(
            text(
                f"""
                SELECT agent_id::text, COALESCE(SUM({tokens}), 0) AS tokens, COALESCE(SUM(cost), 0) AS cost,
                       COUNT(DISTINCT request_id) FILTER (WHERE source = 'agent_stream' AND request_id IS NOT NULL)
                       + COUNT(*) FILTER (WHERE source = 'agent_stream' AND request_id IS NULL) AS requests,
                       COUNT(DISTINCT user_id) AS people
                FROM token_usage WHERE {where} AND agent_id IS NOT NULL
                GROUP BY agent_id ORDER BY cost DESC, tokens DESC, agent_id LIMIT :limit
                """
            ),
            params,
        ).fetchall()
        return {
            "totals": {"tokens": int(totals[0]), "cost": float(totals[1]), "people": int(totals[2])},
            "split": {
                "chats": {"tokens": int(totals[3]), "cost": float(totals[4])},
                "runs": {"tokens": int(totals[5]), "cost": float(totals[6])},
            },
            "by_person": [{"user_id": r[0], "tokens": int(r[1]), "cost": float(r[2])} for r in people],
            "by_agent": [
                {"agent_id": r[0], "tokens": int(r[1]), "cost": float(r[2]), "requests": int(r[3]),
                 "people": int(r[4])}
                for r in agents
            ],
        }

    def tokens_by_model(self, *, start: datetime) -> list[dict]:
        """Return ``{model_id, tokens, cost}`` per model since ``start``, busiest first."""
        result = self._conn.execute(
            text(
                """
                SELECT model_id,
                       COALESCE(SUM(prompt_tokens + generated_tokens), 0) AS tokens,
                       COALESCE(SUM(cost), 0) AS cost
                FROM token_usage
                WHERE timestamp >= :start AND model_id IS NOT NULL
                  AND source <> ALL(:rollup_sources)
                GROUP BY model_id
                ORDER BY tokens DESC, model_id
                """
            ),
            {"start": start, "rollup_sources": list(self.ROLLUP_SOURCES)},
        )
        return [
            {"model_id": row[0], "tokens": int(row[1]), "cost": float(row[2])}
            for row in result.fetchall()
        ]

    # Token usage written outside a user-initiated request (conversation
    # title generation, history compression, RAG question condensing,
    # provider fallback). Mirrors the exclusion list in ``count_in_range``.
    SIDE_CHANNEL_SOURCES = ("title", "compression", "rag_condense", "fallback")

    # Run-level roll-ups that duplicate per-call rows. The scheduler worker
    # used to insert one ``source='schedule'`` row summing a run's tokens,
    # though the run's individual LLM calls were already persisted as
    # ``agent_stream`` rows by the usage decorators. It no longer writes
    # them; rows written before that stay out of every total. A rollup is
    # never used as a fallback: if a per-call insert failed (logged in
    # usage.py), that call's tokens go uncounted, the same loss mode as any
    # other traffic whose insert fails.
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
                       COALESCE(SUM(tu.generated_tokens), 0) AS generated_tokens,
                       COALESCE(SUM(tu.cost), 0) AS cost,
                       -- NULL cache bins mean "provider did not report", so
                       -- they stay out of the sum rather than reading as 0.
                       SUM(tu.cached_tokens) AS cached_tokens,
                       -- The matching denominator: prompt tokens from the
                       -- rows that reported. Dividing ``cached_tokens`` by
                       -- ``prompt_tokens`` instead would understate the hit
                       -- rate by however much traffic ran on a provider that
                       -- reports nothing, since those rows are in one sum but
                       -- not the other.
                       COALESCE(
                           SUM(tu.prompt_tokens)
                               FILTER (WHERE tu.cached_tokens IS NOT NULL),
                           0
                       ) AS cache_eligible_prompt_tokens
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
                "cost": float(row._mapping["cost"]),
                "cached_tokens": (
                    int(row._mapping["cached_tokens"])
                    if row._mapping["cached_tokens"] is not None
                    else None
                ),
                "cache_eligible_prompt_tokens": int(
                    row._mapping["cache_eligible_prompt_tokens"]
                ),
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
        agent_id: Optional[str] = None,
    ) -> int:
        """Count user-initiated requests in the given time range.

        A request = one ``agent_stream`` invocation. Multi-tool agent
        runs produce multiple rows (one per LLM call) tagged with the
        same ``request_id``; we DISTINCT on that to count the request
        once. Pre-migration rows have ``request_id=NULL`` and are
        counted one-per-row via the second branch (back-compat).
        Side-channel sources (``title`` / ``compression`` /
        ``rag_condense`` / ``fallback``) are excluded — they aren't
        user-initiated and shouldn't tick the request limit. ``api_key`` and
        ``agent_id`` together match a row carrying either.
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
        agent_clause = self._agent_clause(api_key, agent_id, params)
        if agent_clause:
            clauses.append(agent_clause)
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
