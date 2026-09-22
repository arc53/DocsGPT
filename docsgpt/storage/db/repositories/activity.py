"""One merged, normalized feed over the instance's three audit journals.

DocsGPT keeps three append-only journals, each written by a different part of
the system and each previously readable only on its own terms:

* ``auth_events`` — identity, access, configuration and (since the data-plane
  hooks) resource mutations.
* ``device_audit_log`` — every remote-device command dispatch and its outcome.
* ``guardrail_events`` — every guardrail decision on a request.

An operator reviewing an incident wants one timeline, not three. This
repository projects all three onto a common row shape and merges them with
``UNION ALL``, so a single ordered, filtered, paginated feed spans the lot.

Two exclusions are deliberate and mirror the per-agent guardrail view: the
``guardrail_events.api_key`` column is a raw agent key, and ``matched_value``
is unredacted source text. Neither is projected here, admin-gated or not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator, Optional, Sequence

from sqlalchemy import Connection, text

from docsgpt.audit_events import category_case_sql


# Columns every branch of the union produces, in order.
ACTIVITY_COLUMNS = (
    "feed",
    "id",
    "event",
    "category",
    "actor_id",
    "target_id",
    "ip",
    "user_agent",
    "outcome",
    "detail",
    "created_at",
)

# Which journal each feed name reads from. Used to skip a branch entirely when
# the category filter cannot match it.
_FEED_CATEGORIES = {"auth": None, "device": "device", "guardrail": "safety"}

_AUTH_BRANCH = f"""
    SELECT 'auth' AS feed,
           id::text AS id,
           event,
           {category_case_sql("event")} AS category,
           actor_id,
           target_id,
           ip,
           user_agent,
           NULL::text AS outcome,
           metadata AS detail,
           created_at
    FROM auth_events
"""

_DEVICE_BRANCH = """
    SELECT 'device' AS feed,
           id::text AS id,
           'device.' || action AS event,
           'device' AS category,
           user_id AS actor_id,
           NULL::text AS target_id,
           NULL::text AS ip,
           NULL::text AS user_agent,
           decision AS outcome,
           jsonb_strip_nulls(jsonb_build_object(
               'device_id', device_id,
               'invocation_id', invocation_id,
               'command', command,
               'working_dir', working_dir,
               'approval_mode', approval_mode,
               'decision_reason', decision_reason,
               'exit_code', exit_code,
               'duration_ms', duration_ms,
               'agent_id', agent_id,
               'conversation_id', conversation_id
           )) AS detail,
           created_at
    FROM device_audit_log
"""

_GUARDRAIL_BRANCH = """
    SELECT 'guardrail' AS feed,
           g.id::text AS id,
           'guardrail.' || g.stage AS event,
           'safety' AS category,
           g.user_id AS actor_id,
           NULL::text AS target_id,
           NULL::text AS ip,
           NULL::text AS user_agent,
           g.outcome,
           jsonb_strip_nulls(jsonb_build_object(
               'check_name', g.check_name,
               'detector_type', g.detector_type,
               'action', g.action,
               'category', g.category,
               'score', g.score,
               'match_count', g.match_count,
               'agent_id', g.agent_id,
               'message_id', g.message_id,
               'request_id', g.request_id,
               'detail', g.detail
           )) AS detail,
           g.created_at
    FROM guardrail_events g
"""

_BRANCHES = {
    "auth": _AUTH_BRANCH,
    "device": _DEVICE_BRANCH,
    "guardrail": _GUARDRAIL_BRANCH,
}


class ActivityRepository:
    """Read-only merged feed over ``auth_events`` + the two side journals."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    @staticmethod
    def _feeds_for(
        feeds: Optional[Sequence[str]], categories: Optional[Sequence[str]]
    ) -> list[str]:
        """Which union branches can still produce a matching row.

        A ``category=device`` filter cannot be satisfied by ``auth_events``, so
        that branch is dropped from the union rather than scanned and
        discarded. ``auth`` spans several categories and is only dropped when
        the filter names none of them.
        """
        selected = list(feeds) if feeds else list(_BRANCHES)
        selected = [feed for feed in selected if feed in _BRANCHES]
        if not categories:
            return selected
        wanted = set(categories)
        fixed_only = {category for category in _FEED_CATEGORIES.values() if category}
        keep = []
        for feed in selected:
            fixed = _FEED_CATEGORIES[feed]
            if fixed is None:
                # ``auth`` spans several categories, so keep it unless the
                # filter names only categories another journal owns outright.
                if wanted - fixed_only:
                    keep.append(feed)
            elif fixed in wanted:
                keep.append(feed)
        return keep

    def _query(
        self,
        *,
        feeds: Optional[Sequence[str]],
        categories: Optional[Sequence[str]],
        events: Optional[Sequence[str]],
        actor_id: Optional[str],
        user_id: Optional[str],
        since: Optional[datetime],
        until: Optional[datetime],
        search: Optional[str],
    ) -> tuple[str, dict]:
        selected = self._feeds_for(feeds, categories)
        if not selected:
            return "", {}
        union = " UNION ALL ".join(_BRANCHES[feed] for feed in selected)

        clauses: list[str] = []
        params: dict[str, Any] = {}
        if categories:
            clauses.append("category = ANY(:categories)")
            params["categories"] = list(categories)
        if events:
            clauses.append("event = ANY(:events)")
            params["events"] = list(events)
        if actor_id:
            clauses.append("actor_id = :actor_id")
            params["actor_id"] = actor_id
        if user_id:
            clauses.append("(actor_id = :user_id OR target_id = :user_id)")
            params["user_id"] = user_id
        if since is not None:
            clauses.append("created_at >= :since")
            params["since"] = since
        if until is not None:
            clauses.append("created_at <= :until")
            params["until"] = until
        if search:
            clauses.append(
                "(actor_id ILIKE :search OR target_id ILIKE :search "
                "OR event ILIKE :search OR ip ILIKE :search "
                "OR COALESCE(outcome, '') ILIKE :search OR detail::text ILIKE :search)"
            )
            params["search"] = f"%{search}%"
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return f"SELECT * FROM ({union}) AS activity {where}", params

    def list(
        self,
        *,
        feeds: Optional[Sequence[str]] = None,
        categories: Optional[Sequence[str]] = None,
        events: Optional[Sequence[str]] = None,
        actor_id: Optional[str] = None,
        user_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return one page of the merged feed, newest first.

        Args:
            feeds: Restrict to named journals (``auth``, ``device``, ``guardrail``).
            categories: Restrict to activity categories.
            events: Restrict to exact event names.
            actor_id: Only rows this user performed.
            user_id: Rows where this user is the actor or the target.
            since: Inclusive lower bound on ``created_at``.
            until: Inclusive upper bound on ``created_at``.
            search: Case-insensitive substring over ids, event, IP and detail.
            limit: Page size.
            offset: Rows to skip.

        Returns:
            Row dicts carrying :data:`ACTIVITY_COLUMNS`.
        """
        sql, params = self._query(
            feeds=feeds,
            categories=categories,
            events=events,
            actor_id=actor_id,
            user_id=user_id,
            since=since,
            until=until,
            search=search,
        )
        if not sql:
            return []
        params.update({"limit": int(limit), "offset": int(offset)})
        result = self._conn.execute(
            text(f"{sql} ORDER BY created_at DESC, feed, id DESC LIMIT :limit OFFSET :offset"),
            params,
        )
        return [dict(row._mapping) for row in result.fetchall()]

    def count(
        self,
        *,
        feeds: Optional[Sequence[str]] = None,
        categories: Optional[Sequence[str]] = None,
        events: Optional[Sequence[str]] = None,
        actor_id: Optional[str] = None,
        user_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        search: Optional[str] = None,
    ) -> int:
        """Total rows matching the same filters as :meth:`list`."""
        sql, params = self._query(
            feeds=feeds,
            categories=categories,
            events=events,
            actor_id=actor_id,
            user_id=user_id,
            since=since,
            until=until,
            search=search,
        )
        if not sql:
            return 0
        scalar = self._conn.execute(
            text(f"SELECT count(*) FROM ({sql}) AS matched"), params
        ).scalar()
        return int(scalar or 0)

    def iter_all(
        self,
        *,
        chunk_size: int = 1000,
        max_rows: int = 100_000,
        **filters: Any,
    ) -> Iterator[dict]:
        """Yield every matching row, newest first, for the export endpoint.

        Pages through the feed rather than materializing it, so an export of a
        large instance streams instead of building the whole result in memory.

        Args:
            chunk_size: Rows fetched per round trip.
            max_rows: Hard ceiling; an export stops here rather than running
                unbounded against a busy instance.
            **filters: As :meth:`list`, minus ``limit`` / ``offset``.

        Yields:
            Row dicts carrying :data:`ACTIVITY_COLUMNS`.
        """
        emitted = 0
        offset = 0
        while emitted < max_rows:
            page = self.list(
                limit=min(chunk_size, max_rows - emitted), offset=offset, **filters
            )
            if not page:
                return
            for row in page:
                yield row
            emitted += len(page)
            offset += len(page)

    def event_names(self) -> list[dict]:
        """Distinct ``(event, category)`` pairs across all three journals.

        Feeds the filter's event picker, so operators choose from what the
        instance actually recorded rather than typing a name from memory.
        """
        union = " UNION ALL ".join(_BRANCHES.values())
        result = self._conn.execute(
            text(
                f"SELECT DISTINCT event, category FROM ({union}) AS activity "
                "ORDER BY category, event"
            )
        )
        return [{"event": row[0], "category": row[1]} for row in result.fetchall()]
