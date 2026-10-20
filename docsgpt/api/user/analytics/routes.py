"""Analytics and reporting routes."""

import datetime
from typing import Optional, Tuple

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from sqlalchemy import Connection, text as _sql_text

from docsgpt import decisions
from docsgpt.activity.flags import list_runs
from docsgpt.activity.now import CHAT_FRESH_SECONDS
from docsgpt.analytics import insights, schema as analytics_schema, topics as analytics_topics
from docsgpt.analytics.config import TAG_ID, AnalyticsConfig
from docsgpt.api import api
from docsgpt.api.user.resource_access import AccessDenied, require, resolve
from docsgpt.api.user.base import (
    generate_date_range,
    generate_hourly_range,
    generate_minute_range,
)
from docsgpt.core.settings import settings
from docsgpt.storage.db.base_repository import like_escape, looks_like_uuid
from docsgpt.storage.db.redaction import redact_secrets
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversation_labels import (
    GAP_GROUPS,
    LOG_LABELS,
    TAG_PREFIX,
    ConversationLabelsRepository,
    Scope,
    log_label_exists,
    log_label_keys,
)
from docsgpt.storage.db.repositories.request_traces import (
    REF_FIELDS as TRACE_REF_FIELDS,
    RequestTracesRepository,
)
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.session import db_readonly


analytics_ns = Namespace(
    "analytics", description="Analytics and reporting operations", path="/api"
)


_FILTER_BUCKETS = {
    "last_hour": ("minute", "%Y-%m-%d %H:%M:00", "YYYY-MM-DD HH24:MI:00"),
    "last_24_hour": ("hour", "%Y-%m-%d %H:00", "YYYY-MM-DD HH24:00"),
    "last_7_days": ("day", "%Y-%m-%d", "YYYY-MM-DD"),
    "last_15_days": ("day", "%Y-%m-%d", "YYYY-MM-DD"),
    "last_30_days": ("day", "%Y-%m-%d", "YYYY-MM-DD"),
}


def _range_for_filter(filter_option: str):
    """Return ``(start_date, end_date, bucket_unit, pg_fmt)`` for the filter.

    Returns ``None`` on invalid filter.
    """
    if filter_option not in _FILTER_BUCKETS:
        return None
    end_date = datetime.datetime.now(datetime.timezone.utc)
    bucket_unit, _py_fmt, pg_fmt = _FILTER_BUCKETS[filter_option]

    if filter_option == "last_hour":
        start_date = end_date - datetime.timedelta(hours=1)
    elif filter_option == "last_24_hour":
        start_date = end_date - datetime.timedelta(hours=24)
    else:
        days = {
            "last_7_days": 6,
            "last_15_days": 14,
            "last_30_days": 29,
        }[filter_option]
        start_date = end_date - datetime.timedelta(days=days)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
    return start_date, end_date, bucket_unit, pg_fmt


def _intervals_for_filter(filter_option, start_date, end_date):
    if filter_option == "last_hour":
        return generate_minute_range(start_date, end_date)
    if filter_option == "last_24_hour":
        return generate_hourly_range(start_date, end_date)
    return generate_date_range(start_date, end_date)


def _resolve_agent(conn, api_key_id, user_id):
    """Access-checked agent lookup for analytics filters.

    Returns ``(agent, api_key, agent_pg_id)``. ``agent`` is ``None`` when
    the id doesn't resolve to an agent the caller can see — callers must
    short-circuit with an empty result, not fall back to sentinel filter
    values. A visible agent needs ``view_logs`` (owner and editors; viewers
    when the owner turns on ``viewers_can_see_logs``), and the caller then
    sees exactly the owner's view of it. ``api_key`` is ``None`` (never
    ``""``) for key-less agents: draft agents store ``key = ''``, and an
    ``''`` filter would match the ``''`` that writers like ``stack_logs``
    stamp on every key-less request — leaking rows across users. NULL
    matches nothing. Accepts UUID or legacy Mongo ObjectId ids.

    Raises:
        AccessDenied: 403 when the agent is visible but ``view_logs`` isn't allowed.
    """
    ra = resolve(conn, "agent", api_key_id, user_id) if api_key_id else None
    if ra is None:
        return None, None, None
    if not ra.can("view_logs"):
        raise AccessDenied(403, "Your access to this agent doesn't include its logs")
    agent = AgentsRepository(conn).get_by_id(ra.resource_id)
    api_key = (agent or {}).get("key") or None
    agent_pg_id = str(agent["id"]) if agent else None
    return agent, api_key, agent_pg_id


def _denied(err: AccessDenied):
    """The JSON error response for an :class:`AccessDenied`."""
    return make_response(jsonify({"success": False, "message": err.message}), err.status)


def _trace_branch(name: str, sources_sql: str, scope: str) -> dict:
    """A ``get_user_logs`` branch listing stored traces of the given sources."""
    return {
        "name": name,
        "level": "CASE WHEN t.status = 'error' THEN 'error' ELSE 'info' END",
        # A search is listed by its query (copied into the small ``summary``
        # at flush so this never detoasts ``spans``); graph builds are named
        # after their source.
        "summary": "COALESCE(t.summary->>'query', t.name, t.source)",
        "ts": "t.started_at",
        "where": [f"t.source IN {sources_sql}", scope],
        "sql": f"""
        SELECT '{name}' AS event_type,
               CAST(t.id AS text) AS id,
               t.user_id AS user_id,
               t.started_at AS timestamp,
               {{level}} AS level,
               t.source AS action,
               {{summary}} AS summary,
               jsonb_build_object(
                   'status', t.status,
                   'source', t.source,
                   'duration_ms', t.duration_ms
               ) AS payload
        FROM request_traces t
        WHERE {{where}}
        """,
    }


def _trace_ref(item: dict) -> Optional[Tuple[str, str]]:
    """The ``(field, value)`` that finds a Logs row's trace, if it has one."""
    event_type = item["event_type"]
    row_id = item["id"].split("-", 1)[1]
    if event_type == "chat":
        return ("request_id", item.get("request_id")) if item.get("request_id") else None
    if event_type in ("system", "webhook"):
        return ("activity_id", item.get("activity_id")) if item.get("activity_id") else None
    if event_type == "workflow":
        return ("workflow_run_id", row_id)
    if event_type == "schedule":
        # The scheduler records the run under its run id.
        return ("request_id", row_id)
    if event_type in ("search", "graph"):
        return ("id", row_id)
    return None


def _merge_trace_summaries(traces: list) -> dict:
    """One Logs-row summary over every trace for it (a turn plus its resumes)."""
    totals: dict = {}
    for trace in traces:
        for key, value in (trace.get("summary") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    if "retrieval_ms" in totals:
        totals["retrieval_ms"] = round(totals["retrieval_ms"], 1)
    return {
        "count": len(traces),
        "duration_ms": sum(int(t.get("duration_ms") or 0) for t in traces),
        "status": traces[-1].get("status"),
        "started_at": traces[0].get("started_at"),
        "summary": totals,
    }


def _attach_trace_summaries(
    conn: Connection, items: list, *, user_id: Optional[str], agent_id: Optional[str]
) -> None:
    """Add a ``trace`` summary to each Logs row that has a stored trace.

    One batched lookup per link field for the whole page, rather than a join
    inside the UNION, so the timeline query is unchanged. Rows without a
    trace (older than the feature, or tracing disabled) get no key.
    """
    refs: dict = {}
    for item in items:
        ref = _trace_ref(item)
        if ref:
            refs.setdefault(ref[0], set()).add(str(ref[1]))
    if not refs:
        return
    found = RequestTracesRepository(conn).summaries_for_refs(
        refs, user_id=user_id, agent_id=agent_id
    )
    for item in items:
        ref = _trace_ref(item)
        if not ref:
            continue
        traces = found.get(ref[0], {}).get(str(ref[1]))
        if traces:
            item["trace"] = {
                "ref": {"field": ref[0], "value": str(ref[1])},
                **_merge_trace_summaries(traces),
            }


@analytics_ns.route("/traces")
class GetTraces(Resource):
    @api.doc(
        description=(
            "Stored execution traces (span timelines) for one Logs row. Pass exactly "
            "one of message_id, request_id, activity_id, workflow_run_id or id; "
            "api_key_id scopes to an agent you own."
        ),
        params={
            "message_id": "Assistant message id",
            "request_id": "Request id (chat turn, scheduled run)",
            "activity_id": "Agent activity id (webhook and system rows)",
            "workflow_run_id": "Workflow run id",
            "id": "Trace id",
            "api_key_id": "Agent id to scope to",
        },
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        refs = [
            (field, request.args.get(field))
            for field in TRACE_REF_FIELDS
            if request.args.get(field)
        ]
        if len(refs) != 1:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Pass exactly one of: " + ", ".join(TRACE_REF_FIELDS),
                    }
                ),
                400,
            )
        field, value = refs[0]
        api_key_id = request.args.get("api_key_id")
        try:
            with db_readonly() as conn:
                agent, _api_key, agent_pg_id = _resolve_agent(conn, api_key_id, user)
                if api_key_id and agent is None:
                    return make_response(jsonify({"success": True, "traces": []}), 200)
                traces = RequestTracesRepository(conn).list_by_ref(
                    field, value, user_id=user, agent_id=agent_pg_id
                )
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(f"Error getting traces: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        for trace in traces:
            trace.pop("_id", None)
        return make_response(jsonify({"success": True, "traces": traces}), 200)


@analytics_ns.route("/get_message_analytics")
class GetMessageAnalytics(Resource):
    get_message_analytics_model = api.model(
        "GetMessageAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=list(_FILTER_BUCKETS.keys()),
            ),
        },
    )

    @api.expect(get_message_analytics_model)
    @api.doc(description="Get message analytics based on filter option")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        window = _range_for_filter(filter_option)
        if window is None:
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, _bucket_unit, pg_fmt = window

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                if api_key_id and agent is None:
                    # Unknown / not-owned agent: empty result, not a
                    # sentinel filter (see _resolve_agent).
                    intervals = _intervals_for_filter(
                        filter_option, start_date, end_date
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "messages": {i: 0 for i in intervals},
                            }
                        ),
                        200,
                    )

                # Count messages per bucket. When filtering by agent the
                # owner-scoped lookup above already gates access, so the
                # user clause is dropped (matching tokens / tools / logs):
                # a shared agent's conversations carry the caller's
                # user_id, and the owner should see that traffic on their
                # own agent's dashboard. Agent matching covers both
                # shapes: external traffic stamps ``api_key``, owner /
                # shared chats stamp ``agent_id``.
                clauses = [
                    "m.timestamp >= :start",
                    "m.timestamp <= :end",
                ]
                params: dict = {
                    "start": start_date,
                    "end": end_date,
                    "fmt": pg_fmt,
                }
                if api_key_id:
                    clauses.append(
                        "(c.api_key = :api_key"
                        " OR c.agent_id = CAST(:agent_pg_id AS uuid))"
                    )
                    params["api_key"] = api_key
                    params["agent_pg_id"] = agent_pg_id
                else:
                    clauses.append("c.user_id = :user_id")
                    params["user_id"] = user
                where = " AND ".join(clauses)
                sql = (
                    "SELECT to_char(m.timestamp AT TIME ZONE 'UTC', :fmt) AS bucket, "
                    "COUNT(*) AS count "
                    "FROM conversation_messages m "
                    "JOIN conversations c ON c.id = m.conversation_id "
                    f"WHERE {where} "
                    "GROUP BY bucket ORDER BY bucket ASC"
                )
                rows = conn.execute(_sql_text(sql), params).fetchall()

            intervals = _intervals_for_filter(filter_option, start_date, end_date)
            daily_messages = {interval: 0 for interval in intervals}
            for row in rows:
                daily_messages[row._mapping["bucket"]] = int(row._mapping["count"])
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(
                f"Error getting message analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "messages": daily_messages}), 200
        )


@analytics_ns.route("/get_token_analytics")
class GetTokenAnalytics(Resource):
    get_token_analytics_model = api.model(
        "GetTokenAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=list(_FILTER_BUCKETS.keys()),
            ),
            "group_by": fields.String(
                required=False,
                description="Second grouping dimension for the series",
                default="none",
                enum=["none", "model", "agent", "source"],
            ),
            "include_side_channel": fields.Boolean(
                required=False,
                description=(
                    "Include non-user-initiated token usage (title "
                    "generation, compression, RAG condensing, fallback)"
                ),
                default=True,
            ),
        },
    )

    @api.expect(get_token_analytics_model)
    @api.doc(description="Get token analytics data")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")
        group_by = data.get("group_by") or "none"
        # ``@api.expect`` documents but never validates/coerces — a JSON
        # string like "false" must not truthy-coerce to True.
        raw_side = data.get("include_side_channel", True)
        if isinstance(raw_side, str):
            include_side_channel = raw_side.strip().lower() not in (
                "false",
                "0",
                "no",
            )
        else:
            include_side_channel = bool(raw_side)

        window = _range_for_filter(filter_option)
        if window is None or group_by not in ("none", "model", "agent", "source"):
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, bucket_unit, _pg_fmt = window

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                if api_key_id and agent is None:
                    # Unknown / not-owned agent: empty result, not a
                    # sentinel filter (see _resolve_agent).
                    rows = []
                else:
                    # The owner-scoped lookup gates access, so the
                    # user_id filter is dropped when agent-filtering
                    # (shared-agent rows carry the caller's user_id).
                    # The agent match is key-OR-id: chat stamps the
                    # key, headless runs stamp agent_id.
                    rows = TokenUsageRepository(conn).bucketed_totals(
                        bucket_unit=bucket_unit,
                        user_id=None if api_key_id else user,
                        api_key=api_key,
                        agent_id=agent_pg_id,
                        timestamp_gte=start_date,
                        timestamp_lt=end_date,
                        group_by=None if group_by == "none" else group_by,
                        include_side_channel=include_side_channel,
                    )

            intervals = _intervals_for_filter(filter_option, start_date, end_date)
            daily_token_usage = {interval: 0 for interval in intervals}
            # ``series`` is the multi-dataset shape the dashboard renders
            # as stacked bars: {series_key: {bucket: tokens}}. Without
            # grouping the two series are the prompt/generated split.
            series: dict = {}
            if group_by == "none":
                series = {
                    "prompt": {interval: 0 for interval in intervals},
                    "generated": {interval: 0 for interval in intervals},
                }
                for entry in rows:
                    bucket = entry["bucket"]
                    daily_token_usage[bucket] = int(
                        entry["prompt_tokens"] + entry["generated_tokens"]
                    )
                    series["prompt"][bucket] = int(entry["prompt_tokens"])
                    series["generated"][bucket] = int(entry["generated_tokens"])
            else:
                for entry in rows:
                    bucket = entry["bucket"]
                    total = int(entry["prompt_tokens"] + entry["generated_tokens"])
                    daily_token_usage[bucket] = (
                        daily_token_usage.get(bucket, 0) + total
                    )
                    key = entry["group_key"]
                    if key not in series:
                        series[key] = {interval: 0 for interval in intervals}
                    series[key][bucket] = series[key].get(bucket, 0) + total
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(
                f"Error getting token analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "token_usage": daily_token_usage,
                    "group_by": group_by,
                    "series": series,
                }
            ),
            200,
        )


@analytics_ns.route("/get_feedback_analytics")
class GetFeedbackAnalytics(Resource):
    get_feedback_analytics_model = api.model(
        "GetFeedbackAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=list(_FILTER_BUCKETS.keys()),
            ),
        },
    )

    @api.expect(get_feedback_analytics_model)
    @api.doc(description="Get feedback analytics data")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        window = _range_for_filter(filter_option)
        if window is None:
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, _bucket_unit, pg_fmt = window

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                if api_key_id and agent is None:
                    intervals = _intervals_for_filter(
                        filter_option, start_date, end_date
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "feedback": {
                                    i: {"positive": 0, "negative": 0}
                                    for i in intervals
                                },
                            }
                        ),
                        200,
                    )

                # Feedback lives inside the ``conversation_messages.feedback``
                # JSONB as ``{"text": "like"|"dislike", "timestamp": "..."}``.
                # There is no scalar ``feedback_timestamp`` column — extract
                # the timestamp from the JSONB and cast it to timestamptz for
                # the range filter + bucket grouping.
                clauses = [
                    "m.feedback IS NOT NULL",
                    "(m.feedback->>'timestamp')::timestamptz >= :start",
                    "(m.feedback->>'timestamp')::timestamptz <= :end",
                ]
                params: dict = {
                    "start": start_date,
                    "end": end_date,
                    "fmt": pg_fmt,
                }
                if api_key_id:
                    # Owner-gated agent match (see GetMessageAnalytics):
                    # drop the user clause so shared-agent feedback is
                    # visible to the owner, consistent with the other
                    # per-agent charts.
                    clauses.append(
                        "(c.api_key = :api_key"
                        " OR c.agent_id = CAST(:agent_pg_id AS uuid))"
                    )
                    params["api_key"] = api_key
                    params["agent_pg_id"] = agent_pg_id
                else:
                    clauses.append("c.user_id = :user_id")
                    params["user_id"] = user
                where = " AND ".join(clauses)
                sql = (
                    "SELECT to_char("
                    "(m.feedback->>'timestamp')::timestamptz AT TIME ZONE 'UTC', :fmt"
                    ") AS bucket, "
                    "SUM(CASE WHEN m.feedback->>'text' = 'like' THEN 1 ELSE 0 END) AS positive, "
                    "SUM(CASE WHEN m.feedback->>'text' = 'dislike' THEN 1 ELSE 0 END) AS negative "
                    "FROM conversation_messages m "
                    "JOIN conversations c ON c.id = m.conversation_id "
                    f"WHERE {where} "
                    "GROUP BY bucket ORDER BY bucket ASC"
                )
                rows = conn.execute(_sql_text(sql), params).fetchall()

            intervals = _intervals_for_filter(filter_option, start_date, end_date)
            daily_feedback = {
                interval: {"positive": 0, "negative": 0} for interval in intervals
            }
            for row in rows:
                bucket = row._mapping["bucket"]
                daily_feedback[bucket] = {
                    "positive": int(row._mapping["positive"] or 0),
                    "negative": int(row._mapping["negative"] or 0),
                }
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(
                f"Error getting feedback analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "feedback": daily_feedback}), 200
        )


@analytics_ns.route("/get_tool_analytics")
class GetToolAnalytics(Resource):
    get_tool_analytics_model = api.model(
        "GetToolAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=list(_FILTER_BUCKETS.keys()),
            ),
        },
    )

    @api.expect(get_tool_analytics_model)
    @api.doc(description="Get tool call analytics from the tool execution journal")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        window = _range_for_filter(filter_option)
        if window is None:
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, _bucket_unit, _pg_fmt = window

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                if api_key_id and agent is None:
                    return make_response(
                        jsonify({"success": True, "tools": []}), 200
                    )

                # Terminal rows only. ``proposed`` (pending) and
                # ``executed`` (ran, not yet finalized) are non-terminal:
                # counting them inflates ``calls`` and — since the client
                # computes successful = calls - failures — renders them as
                # phantom successes that later flip to failures when the
                # reconciler escalates a stuck row. ``confirmed`` is the
                # only success state; ``failed`` the only failure.
                clauses = [
                    "t.status IN ('confirmed', 'failed')",
                    "t.attempted_at >= :start",
                    "t.attempted_at <= :end",
                ]
                params: dict = {
                    "start": start_date,
                    "end": end_date,
                }
                join = (
                    "LEFT JOIN conversation_messages m ON m.id = t.message_id "
                    "LEFT JOIN conversations c ON c.id = m.conversation_id "
                )
                if api_key_id:
                    # Match by direct agent stamp (headless), the
                    # conversation's api_key (external chat), or the
                    # conversation's agent_id (owner chats / pre-0018
                    # rows). The owner-scoped lookup gates access, so
                    # no user clause — the owner also sees shared-agent
                    # traffic logged under callers' user_ids.
                    clauses.append(
                        "(t.agent_id = CAST(:agent_pg_id AS uuid)"
                        " OR c.api_key = :api_key"
                        " OR c.agent_id = CAST(:agent_pg_id AS uuid))"
                    )
                    params["agent_pg_id"] = agent_pg_id
                    params["api_key"] = api_key
                else:
                    # ``t.user_id`` is stamped at propose time (0018);
                    # pre-migration rows fall back to the parent
                    # message's user (LEFT join — headless runs have no
                    # message). OR rather than COALESCE keeps the first
                    # arm index-sargable.
                    clauses.append(
                        "(t.user_id = :user_id OR m.user_id = :user_id)"
                    )
                    params["user_id"] = user
                where = " AND ".join(clauses)
                sql = (
                    "SELECT t.tool_name, "
                    "COUNT(*) AS calls, "
                    "COUNT(*) FILTER (WHERE t.status = 'failed') AS failures "
                    "FROM tool_call_attempts t "
                    f"{join}"
                    f"WHERE {where} "
                    "GROUP BY t.tool_name "
                    "ORDER BY calls DESC"
                )
                rows = conn.execute(_sql_text(sql), params).fetchall()

            tools = [
                {
                    "tool_name": row._mapping["tool_name"],
                    "calls": int(row._mapping["calls"]),
                    "failures": int(row._mapping["failures"]),
                }
                for row in rows
            ]
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(
                f"Error getting tool analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "tools": tools}), 200)


@analytics_ns.route("/get_schedule_analytics")
class GetScheduleAnalytics(Resource):
    get_schedule_analytics_model = api.model(
        "GetScheduleAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=list(_FILTER_BUCKETS.keys()),
            ),
        },
    )

    @api.expect(get_schedule_analytics_model)
    @api.doc(description="Get scheduled agent run outcomes over time")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        window = _range_for_filter(filter_option)
        if window is None:
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, _bucket_unit, pg_fmt = window

        try:
            with db_readonly() as conn:
                agent, _api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                if api_key_id and agent is None:
                    intervals = _intervals_for_filter(
                        filter_option, start_date, end_date
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "runs": {
                                    i: {
                                        "completed": 0,
                                        "failed": 0,
                                        "skipped": 0,
                                    }
                                    for i in intervals
                                },
                            }
                        ),
                        200,
                    )

                # A run's effective time is when it finished (fell back to
                # started/scheduled for runs that never got that far).
                ts = "COALESCE(r.finished_at, r.started_at, r.scheduled_for)"
                clauses = [
                    f"{ts} >= :start",
                    f"{ts} <= :end",
                ]
                params: dict = {
                    "start": start_date,
                    "end": end_date,
                    "fmt": pg_fmt,
                }
                if api_key_id:
                    # Owner-gated agent match: drop the user clause so a
                    # shared agent's runs (created by callers under their
                    # own user_id via the scheduler tool) are visible to
                    # the owner, consistent with the per-agent timeline.
                    clauses.append("r.agent_id = CAST(:agent_id AS uuid)")
                    params["agent_id"] = agent_pg_id
                else:
                    clauses.append("r.user_id = :user_id")
                    params["user_id"] = user
                where = " AND ".join(clauses)
                # The worker writes ``success`` / ``failed`` / ``timeout`` /
                # ``skipped`` (scheduler_worker.py); ``completed`` is kept in
                # the success bucket defensively. Timeouts count as failures.
                sql = (
                    f"SELECT to_char({ts} AT TIME ZONE 'UTC', :fmt) AS bucket, "
                    "COUNT(*) FILTER (WHERE r.status IN ('success', 'completed')) AS completed, "
                    "COUNT(*) FILTER (WHERE r.status IN ('failed', 'timeout')) AS failed, "
                    "COUNT(*) FILTER (WHERE r.status = 'skipped') AS skipped "
                    "FROM schedule_runs r "
                    f"WHERE {where} "
                    "GROUP BY bucket ORDER BY bucket ASC"
                )
                rows = conn.execute(_sql_text(sql), params).fetchall()

            intervals = _intervals_for_filter(filter_option, start_date, end_date)
            runs = {
                interval: {"completed": 0, "failed": 0, "skipped": 0}
                for interval in intervals
            }
            for row in rows:
                runs[row._mapping["bucket"]] = {
                    "completed": int(row._mapping["completed"] or 0),
                    "failed": int(row._mapping["failed"] or 0),
                    "skipped": int(row._mapping["skipped"] or 0),
                }
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(
                f"Error getting schedule analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "runs": runs}), 200)


def _analytics_available() -> bool:
    """Whether the operator lets the model label conversations: the switch, with the model available."""
    return bool(settings.DECISION_ANALYTICS_ENABLED and decisions.available())


def _agent_analytics(agent: Optional[dict]) -> AnalyticsConfig:
    return AnalyticsConfig.parse(((agent or {}).get("config") or {}).get("analytics"))


def _label_scope(user: str, api_key: Optional[str], agent_pg_id: Optional[str]) -> Scope:
    """An agent's labels (all its traffic, as its owner sees it), else the caller's own."""
    if agent_pg_id:
        return Scope(agent_id=agent_pg_id, api_key=api_key)
    return Scope(user_id=user)


def _previous_start(start: datetime.datetime, end: datetime.datetime) -> datetime.datetime:
    """The start of the window of equal length just before ``[start, end]``."""
    return start - (end - start)


def _utc_iso(value) -> Optional[str]:
    if not hasattr(value, "astimezone"):
        return value
    return value.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


_EMPTY_COVERAGE = {
    "turns": 0, "labelled_turns": 0, "replies": 0, "labelled_replies": 0,
    "conversations": 0, "labelled_conversations": 0, "unlabelled_recent_turns": 0, "unlabelled_older_turns": 0,
}


@analytics_ns.route("/get_conversation_insights")
class GetConversationInsights(Resource):
    get_conversation_insights_model = api.model(
        "GetConversationInsightsModel",
        {
            "api_key_id": fields.String(required=False, description="Agent id"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=list(_FILTER_BUCKETS.keys()),
            ),
        },
    )

    @api.expect(get_conversation_insights_model)
    @api.doc(
        description=(
            "Insights from the decision model's labels: per label and option the "
            "expected count and its rate with a 95% interval widened by the label's calibration "
            "error, each label's tier, the same per time bucket, label coverage and the language "
            "mix. answer_status rates are over requests (not over greetings). 'available' is the "
            "operator switch (DECISION_ANALYTICS_ENABLED with the model available); 'enabled' is "
            "that and the agent's own analytics switch. The sweep labels only the last 'backfill_days' "
            "(from 'labelling_from'), so coverage splits unlabelled answers into 'unlabelled_recent_turns' "
            "(still to be labelled) and 'unlabelled_older_turns' (never labelled without a backfill)."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        window = _range_for_filter(filter_option)
        if window is None:
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, _bucket_unit, pg_fmt = window
        available = _analytics_available()
        backfill_days = settings.ANALYTICS_BACKFILL_DAYS
        labelling_from = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=backfill_days)
        result = {
            "success": True,
            "enabled": False,
            "available": available,
            "backfill_days": backfill_days,
            "labelling_from": _utc_iso(labelling_from),
            "coverage": dict(_EMPTY_COVERAGE),
            "languages": {},
            "language_warnings": [],
            "tags": [],
            "totals": {},
            "series": [],
        }

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(conn, api_key_id, user)
                if api_key_id and agent is None:
                    return make_response(jsonify(result), 200)
                config = _agent_analytics(agent)
                result["enabled"] = available and (agent is None or config.enabled)
                if agent is not None:
                    result["tags"] = [{"id": tag.id, "name": tag.name} for tag in config.tags]
                if not result["enabled"]:
                    return make_response(jsonify(result), 200)

                scope = _label_scope(user, api_key, agent_pg_id)
                repo = ConversationLabelsRepository(conn)
                schema_hash = analytics_schema.SCHEMA_HASH
                labels = [*insights.TOTAL_LABELS, *(f"{TAG_PREFIX}{tag['id']}" for tag in result["tags"])]
                result["coverage"] = repo.coverage(scope, schema_hash, start_date, end_date, labelling_from)
                counts = repo.label_counts(scope, schema_hash, start_date, end_date, labels)
                sums = repo.label_sums(scope, schema_hash, start_date, end_date, labels)
                bucket_counts = repo.bucket_counts(
                    scope, schema_hash, start_date, end_date, insights.SERIES_LABELS, pg_fmt
                )
                bucket_sums = repo.label_sums(
                    scope, schema_hash, start_date, end_date, insights.SERIES_LABELS, bucket_format=pg_fmt
                )

            totals = insights.totals(labels, counts, sums)
            result["totals"] = totals
            result["languages"] = insights.languages(counts)
            result["language_warnings"] = insights.language_warnings(counts)
            result["series"] = insights.series(
                _intervals_for_filter(filter_option, start_date, end_date),
                insights.SERIES_LABELS,
                bucket_counts,
                bucket_sums,
                {label: list(totals[label]["options"]) for label in insights.SERIES_LABELS if label in totals},
            )
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(
                f"Error getting conversation insights: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(result), 200)


#: Most docs-gap groups a request may ask for, and the default.
_MAX_GAP_GROUPS = 50
_DEFAULT_GAP_GROUPS = 25
#: Example questions per docs-gap group.
_GAP_EXAMPLES = 5
#: Groups with fewer expected gaps are left out: they would show as 0.
_MIN_GROUP_GAPS = 0.5


@analytics_ns.route("/get_docs_gaps")
class GetDocsGaps(Resource):
    get_docs_gaps_model = api.model(
        "GetDocsGapsModel",
        {
            "api_key_id": fields.String(required=False, description="Agent id"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=list(_FILTER_BUCKETS.keys()),
            ),
            "group_by": fields.String(
                required=False,
                description=(
                    "Group by the effective topic, or by the source or page of the "
                    "turn's first retrieved chunk"
                ),
                default="page",
                enum=list(GAP_GROUPS),
            ),
            "limit": fields.Integer(
                required=False,
                description=f"Most groups returned (1-{_MAX_GAP_GROUPS})",
                default=_DEFAULT_GAP_GROUPS,
            ),
        },
    )

    @api.expect(get_docs_gaps_model)
    @api.doc(
        description=(
            "Docs gaps: answers that fell short because the docs do not cover the question, as "
            "expected counts (sums of the decision model's probabilities) per group, with the "
            "group's rate over its answers and a 95% interval, the window just before for the "
            "trend, and up to five example questions (gaps at even odds or better). Groups with "
            "under half an expected gap are left out; key null means no source was retrieved. "
            "previous_labelled counts the labelled answers in the window before, so a group with no "
            "earlier gaps can be told from a window that was never labelled; by page, each row's "
            "source names the source most of its answers retrieved the page from (null if unknown)."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")
        group_by = data.get("group_by") or "page"
        try:
            limit = int(data.get("limit") or _DEFAULT_GAP_GROUPS)
        except (TypeError, ValueError):
            limit = 0
        window = _range_for_filter(filter_option)
        if window is None or group_by not in GAP_GROUPS or not 1 <= limit <= _MAX_GAP_GROUPS:
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, _bucket_unit, _pg_fmt = window
        result = {"success": True, "enabled": False, "group_by": group_by, "previous_labelled": 0, "rows": []}

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(conn, api_key_id, user)
                if api_key_id and agent is None:
                    return make_response(jsonify(result), 200)
                result["enabled"] = _analytics_available() and (
                    agent is None or _agent_analytics(agent).enabled
                )
                if not result["enabled"]:
                    return make_response(jsonify(result), 200)
                scope = _label_scope(user, api_key, agent_pg_id)
                repo = ConversationLabelsRepository(conn)
                schema_hash = analytics_schema.SCHEMA_HASH
                previous_start = _previous_start(start_date, end_date)
                groups = repo.gap_groups(
                    group_by, scope, schema_hash, start_date, end_date,
                    previous_start, limit, _MIN_GROUP_GAPS,
                )
                result["previous_labelled"] = repo.gap_labelled(
                    scope, schema_hash, previous_start, start_date
                )
                examples = repo.gap_examples(
                    group_by, scope, schema_hash, start_date, end_date,
                    [group["key"] for group in groups],
                    settings.ANALYTICS_FILTER_MIN_PROBABILITY, _GAP_EXAMPLES,
                ) if groups else []
                source_ids = {"source": "key", "page": "source_id"}.get(group_by)
                names = (
                    repo.source_names(group[source_ids] for group in groups)
                    if source_ids else {}
                )

            by_key: dict = {}
            for example in examples:
                by_key.setdefault(example["key"], []).append(
                    {
                        "message_id": example["message_id"],
                        "conversation_id": example["conversation_id"],
                        "prompt": example["prompt"] or "",
                        "p": round(float(example["p"] or 0), 4),
                        "timestamp": _utc_iso(example["timestamp"]),
                    }
                )
            result["rows"] = [
                insights.gap_row(
                    group,
                    by_key.get(group["key"], []),
                    names.get(group["key"], group["key"]) if group_by == "source" else group["name"],
                    names.get(group["source_id"]) if group_by == "page" else None,
                )
                for group in groups
            ]
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(f"Error getting docs gaps: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(result), 200)


@analytics_ns.route("/analytics/topic_suggestions")
class GetTopicSuggestions(Resource):
    @api.doc(
        description=(
            "The topic list an agent's sources give (its analytics topics in 'auto' mode), for "
            "filling a custom list: one topic per documentation section, described by up to five "
            "page titles. Needs edit access to the agent."
        ),
        params={"agent_id": "Agent id"},
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        agent_id = request.args.get("agent_id")
        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "agent_id is required"}), 400
            )
        try:
            with db_readonly() as conn:
                access = require(conn, "agent", agent_id, user, "edit")
                agent = AgentsRepository(conn).get_by_id(access.resource_id)
                if agent is None:
                    raise AccessDenied(404, "Agent not found")
                suggested = analytics_topics.suggestions(conn, agent)
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(f"Error suggesting topics: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "topics": suggested}), 200)


# Scheduled runs the timeline lists: running ones and every finished state the
# worker writes (``completed`` kept defensively).
_SCHEDULE_LOG_STATUSES = "('pending', 'running', 'success', 'completed', 'failed', 'timeout', 'skipped')"


_UUID_RE = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
# A chat Logs row's message, cast only when the stored id is a UUID so an odd
# legacy value cannot fail the whole query.
_LOG_MESSAGE_ID = (
    "CASE WHEN l.data->>'message_id' ~* :uuid_re "
    "THEN CAST(l.data->>'message_id' AS uuid) END"
)
_MAX_PASSTHROUGH_FILTERS = 8


class _BadLogFilter(Exception):
    """A Logs row filter with the wrong shape; ``message`` is user-facing."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _parse_iso_moment(value, field: str) -> Optional[datetime.datetime]:
    """An ISO 8601 moment from a filter field (UTC when it names no zone)."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise _BadLogFilter(f"{field} must be an ISO 8601 string")
    try:
        moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _BadLogFilter(f"{field} must be an ISO 8601 string")
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def _passthrough_filter_value(value) -> str:
    """A filter value as Postgres' ``->>`` renders the stored JSON scalar."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _log_filters(data: dict) -> dict:
    """The Logs request's row filters, validated.

    Args:
        data: The request body.

    Returns:
        ``conversation_id``, ``passthrough`` (``[(key, text value)]``),
        ``feedback``, ``label``, ``date_from`` and ``date_to``; each ``None``
        when unset.

    Raises:
        _BadLogFilter: A filter has the wrong shape.
    """
    conversation_id = data.get("conversation_id") or None
    if conversation_id is not None and not looks_like_uuid(str(conversation_id)):
        raise _BadLogFilter("conversation_id must be a UUID")
    label = data.get("label") or None
    if label is not None and not (
        isinstance(label, str)
        and (
            label in LOG_LABELS
            or (label.startswith(TAG_PREFIX) and TAG_ID.match(label[len(TAG_PREFIX):]))
        )
    ):
        raise _BadLogFilter(
            "label must be one of " + ", ".join(LOG_LABELS) + " or tag:<id>"
        )
    feedback = data.get("feedback") or None
    if feedback not in (None, "like", "dislike"):
        raise _BadLogFilter("feedback must be 'like' or 'dislike'")
    raw = data.get("passthrough")
    passthrough = None
    if raw not in (None, {}):
        if not isinstance(raw, dict) or len(raw) > _MAX_PASSTHROUGH_FILTERS:
            raise _BadLogFilter(
                f"passthrough must be an object of at most {_MAX_PASSTHROUGH_FILTERS} keys"
            )
        passthrough = []
        for key, value in raw.items():
            if not isinstance(key, str) or not key or not isinstance(value, (str, int, float, bool)):
                raise _BadLogFilter("passthrough filter values must be strings, numbers or booleans")
            passthrough.append((key, _passthrough_filter_value(value)))
    date_from = _parse_iso_moment(data.get("date_from"), "date_from")
    date_to = _parse_iso_moment(data.get("date_to"), "date_to")
    return {
        "conversation_id": str(conversation_id) if conversation_id else None,
        "passthrough": passthrough,
        "feedback": feedback,
        "label": label,
        "date_from": date_from,
        "date_to": date_to,
    }


def _attach_message_feedback(conn: Connection, items: list) -> None:
    """Add each chat row's feedback (``{text, timestamp}``) from its message, in one lookup."""
    ids = {
        str(item["message_id"])
        for item in items
        if item["event_type"] == "chat"
        and not item.get("running")
        and item.get("message_id")
        and looks_like_uuid(str(item["message_id"]))
    }
    if not ids:
        return
    rows = conn.execute(
        _sql_text(
            "SELECT CAST(id AS text) AS id, feedback, CAST(conversation_id AS text) AS conversation_id "
            "FROM conversation_messages WHERE id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": sorted(ids)},
    ).fetchall()
    found = {row._mapping["id"]: row._mapping for row in rows}
    for item in items:
        message = found.get(str(item.get("message_id") or ""))
        if message is None:
            continue
        if message["feedback"]:
            item["feedback"] = message["feedback"]
        # Rows logged before the conversation id was stored on them.
        if not item.get("conversation_id"):
            item["conversation_id"] = message["conversation_id"]


def _attach_labels(conn: Connection, items: list) -> dict:
    """Add each finished chat row's analytics ``labels`` (chip keys at even odds or better), in one lookup.

    Reaction labels (frustrated, asked for a person, negative reaction) sit on
    the user message that showed them; tags on every turn of their
    conversation. Rows with none get an empty list.

    Returns:
        ``{tag id: name}`` for the tags on the page, from each row's agent.
    """
    chats = [
        item for item in items
        if item["event_type"] == "chat" and not item.get("running")
    ]
    for item in chats:
        item["labels"] = []
    ids = {
        str(item["message_id"]) for item in chats
        if item.get("message_id") and looks_like_uuid(str(item["message_id"]))
    }
    if not ids:
        return {}
    repo = ConversationLabelsRepository(conn)
    rows = repo.log_rows(ids, analytics_schema.SCHEMA_HASH)
    by_message: dict = {}
    for row in rows:
        by_message.setdefault(row["target"], []).append(row)
    threshold = settings.ANALYTICS_FILTER_MIN_PROBABILITY
    tags: set = set()
    for item in chats:
        keys = log_label_keys(by_message.get(str(item.get("message_id") or ""), []), threshold)
        item["labels"] = keys
        tags.update(key[len(TAG_PREFIX):] for key in keys if key.startswith(TAG_PREFIX))
    if not tags:
        return {}
    agents = {row["agent_id"] for row in rows if row["agent_id"] and row["label"].startswith(TAG_PREFIX)}
    names = repo.tag_names(agents)
    return {tag: names[tag] for tag in sorted(tags) if tag in names}


def _running_webhook_rows(owner_id: str, agent_id: Optional[str], search: Optional[str]) -> list:
    """Timeline rows for the webhook runs going on now.

    Args:
        owner_id: Whose markers to read (an agent's owner on agent logs).
        agent_id: Only this agent's runs, when set.
        search: The timeline's search text, matched against the run summary.

    Returns:
        Rows shaped like the timeline's, newest first.
    """
    needle = (search or "").lower()
    rows = []
    for marker in list_runs(owner_id):
        if marker.get("kind", "webhook") != "webhook":
            continue
        if agent_id and str(marker.get("agent_id") or "") != str(agent_id):
            continue
        summary = marker.get("summary") or marker.get("agent_name") or ""
        if needle and needle not in summary.lower():
            continue
        started = datetime.datetime.fromtimestamp(
            float(marker.get("started_at") or 0), tz=datetime.timezone.utc
        ).isoformat()
        rows.append(
            {
                "id": f"webhook-run-{marker.get('id')}",
                "event_type": "webhook",
                "action": "webhook_run",
                "level": "info",
                "user": owner_id,
                "question": summary,
                "timestamp": started,
                "running": True,
                "agent_id": marker.get("agent_id"),
                "started_at": started,
            }
        )
    return sorted(rows, key=lambda row: row["timestamp"], reverse=True)


def _merge_by_time(rows: list, extra: list) -> list:
    """Place ``extra`` rows among a page's rows by time, newest first.

    The page keeps every row it had (its paging is unchanged); an extra row
    older than the whole page goes at its end.
    """
    if not extra:
        return rows

    def _at(row: dict) -> datetime.datetime:
        try:
            parsed = datetime.datetime.fromisoformat(str(row.get("timestamp")))
        except ValueError:
            return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)

    return sorted(rows + extra, key=_at, reverse=True)


@analytics_ns.route("/get_user_logs")
class GetUserLogs(Resource):
    get_user_logs_model = api.model(
        "GetUserLogsModel",
        {
            "page": fields.Integer(
                required=False,
                description="Page number for pagination",
                default=1,
            ),
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "page_size": fields.Integer(
                required=False,
                description="Number of logs per page",
                default=10,
            ),
            "level": fields.String(
                required=False,
                description="Filter by log level",
                enum=["info", "error", "warning"],
            ),
            "event_type": fields.String(
                required=False,
                description="Filter by event source",
                enum=[
                    "chat", "schedule", "webhook", "workflow", "system", "search", "graph",
                ],
            ),
            "search": fields.String(
                required=False, description="Substring filter on the summary"
            ),
            "conversation_id": fields.String(
                required=False,
                description="Only rows of this conversation (chat turns and scheduled runs)",
            ),
            "passthrough": fields.Raw(
                required=False,
                description=(
                    "Only chat turns whose passthrough values match every "
                    "given key, compared as text, e.g. {\"user_id\": \"42\"}"
                ),
            ),
            "feedback": fields.String(
                required=False,
                description="Only chat turns rated this way",
                enum=["like", "dislike"],
            ),
            "label": fields.String(
                required=False,
                description=(
                    "Only chat turns the decision model labelled this way at "
                    "ANALYTICS_FILTER_MIN_PROBABILITY or better: one of "
                    + ", ".join(LOG_LABELS)
                    + ", or tag:<id> (a tag of the turn's conversation)"
                ),
            ),
            "date_from": fields.String(
                required=False, description="Rows at or after this ISO 8601 moment"
            ),
            "date_to": fields.String(
                required=False, description="Rows before this ISO 8601 moment"
            ),
        },
    )

    @api.expect(get_user_logs_model)
    @api.doc(
        description=(
            "Get user activity logs with pagination. Merges chat answers "
            "(user_logs), request errors (stack_logs) and scheduled agent "
            "runs (schedule_runs) into one timeline. Runs are ordered by "
            "their start time; ones still going (answers, scheduled, "
            "workflow and webhook runs) carry running: true until their "
            "finished row replaces them. Finished chat rows carry 'labels', "
            "the analytics label keys at ANALYTICS_FILTER_MIN_PROBABILITY "
            "or better, and 'tag_names' names the tags on the page."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        try:
            page = max(1, int(data.get("page") or 1))
            page_size = max(1, min(100, int(data.get("page_size") or 10)))
        except (TypeError, ValueError):
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        api_key_id = data.get("api_key_id")
        # An empty value (a tool that fills every field) means no filter.
        level = data.get("level") or None
        event_type = data.get("event_type") or None
        search = data.get("search")
        if level not in (None, "info", "error", "warning") or event_type not in (
            None,
            "chat",
            "schedule",
            "webhook",
            "workflow",
            "system",
            "search",
            "graph",
        ):
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        try:
            filters = _log_filters(data)
        except _BadLogFilter as bad:
            return make_response(jsonify({"success": False, "message": bad.message}), 400)

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                if api_key_id and agent is None:
                    # Unknown / not-owned agent: empty page, not a
                    # sentinel filter (see _resolve_agent).
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "logs": [],
                                "page": page,
                                "page_size": page_size,
                                "has_more": False,
                                "tag_names": {},
                            }
                        ),
                        200,
                    )
                params: dict = {
                    # Agent-scoped logs are the owner's view of the agent.
                    "user_id": agent["user_id"] if agent else user,
                    "limit": page_size + 1,
                    "offset": (page - 1) * page_size,
                }

                # ``schedule`` / ``webhook`` errors are first-class events in
                # their own branches; keep them out of ``system`` so a failed
                # run doesn't appear twice. A failed webhook activity writes
                # both an error row and an info row for the same activity_id
                # (logging.py:_consume_and_log); NOT-EXISTS drops the info twin.
                webhook_dedupe = (
                    "NOT (s.level = 'info' AND EXISTS ("
                    "SELECT 1 FROM stack_logs e "
                    "WHERE e.activity_id = s.activity_id "
                    "AND e.level = 'error'))"
                )
                # A failed chat turn now writes its own chat row (level
                # ``error``) linked to its trace; the agent's error row for
                # the same activity would list the failure twice. Rows from
                # before execution traces, or with tracing off, have no such
                # trace and still show here.
                chat_failure_dedupe = (
                    "NOT EXISTS (SELECT 1 FROM request_traces t "
                    "WHERE t.activity_id = s.activity_id "
                    "AND t.source IN ('stream', 'answer', 'v1'))"
                )
                if api_key_id:
                    # The owner-scoped lookup gates access, so the
                    # chat/webhook/system branches match on the agent
                    # key/id alone — the owner also sees shared-agent
                    # traffic logged under callers' user_ids. The
                    # agent_id arm covers key-less (draft) agents,
                    # whose owner chats log a null api_key.
                    params["api_key"] = api_key
                    params["agent_pg_id"] = agent_pg_id
                    params["agent_workflow_id"] = (
                        str(agent["workflow_id"])
                        if agent and agent.get("workflow_id")
                        else None
                    )
                    chat_where = [
                        "(l.data->>'api_key' = :api_key"
                        " OR l.data->>'agent_id' = :agent_pg_id)"
                    ]
                    # ``stack_logs.agent_id`` (0026) is the stable join key;
                    # ``api_key`` is mutable (agents rotate keys), so match the
                    # id first and keep the key arm for rows predating the
                    # backfill / any null agent_id.
                    stack_agent_match = (
                        "(s.agent_id = CAST(:agent_pg_id AS uuid)"
                        " OR s.api_key = :api_key)"
                    )
                    webhook_where = [
                        "COALESCE(s.endpoint, '') = 'webhook'",
                        stack_agent_match,
                        webhook_dedupe,
                    ]
                    system_where = [
                        "s.level = 'error'",
                        "COALESCE(s.endpoint, '') NOT IN ('webhook', 'schedule')",
                        stack_agent_match,
                        chat_failure_dedupe,
                    ]
                    # Owner-gated agent match: drop the user clause so a
                    # shared agent's runs (stamped with the caller's
                    # user_id by the scheduler tool) appear on the owner's
                    # per-agent timeline, consistent with the chat branch.
                    schedule_where = [
                        f"r.status IN {_SCHEDULE_LOG_STATUSES}",
                        "r.agent_id = CAST(:agent_pg_id AS uuid)",
                    ]
                    # Every caller's answers on the agent, API and shared
                    # ones included (hidden conversations).
                    running_chat_where = ["c.agent_id = CAST(:agent_pg_id AS uuid)"]
                    workflow_where = [
                        "wr.user_id = :user_id",
                        "wr.workflow_id = CAST(:agent_workflow_id AS uuid)",
                    ]
                    trace_scope = "t.agent_id = CAST(:agent_pg_id AS uuid)"
                else:
                    chat_where = ["l.user_id = :user_id"]
                    webhook_where = [
                        "s.user_id = :user_id",
                        "COALESCE(s.endpoint, '') = 'webhook'",
                        webhook_dedupe,
                    ]
                    system_where = [
                        "s.user_id = :user_id",
                        "s.level = 'error'",
                        "COALESCE(s.endpoint, '') NOT IN ('webhook', 'schedule')",
                        chat_failure_dedupe,
                    ]
                    schedule_where = [
                        "r.user_id = :user_id",
                        f"r.status IN {_SCHEDULE_LOG_STATUSES}",
                    ]
                    running_chat_where = ["m.user_id = :user_id"]
                    workflow_where = ["wr.user_id = :user_id"]
                    trace_scope = "t.user_id = :user_id"

                # One normalized timeline over five event sources.
                # ``payload`` carries the per-type detail; the outer query
                # paginates the merged, time-ordered result. level /
                # event_type / search are pushed into each branch so a
                # filtered request only scans the branches it can match.
                branches = [
                    {
                        "name": "chat",
                        "level": "COALESCE(l.data->>'level', 'info')",
                        "summary": "l.data->>'question'",
                        "ts": "l.timestamp",
                        # Rows logged before the id was stored on them are
                        # matched through their message.
                        "conversation": (
                            "(l.data->>'conversation_id' = :conversation_id"
                            " OR (l.data->>'conversation_id' IS NULL AND EXISTS ("
                            "SELECT 1 FROM conversation_messages fm"
                            f" WHERE fm.id = {_LOG_MESSAGE_ID}"
                            " AND fm.conversation_id = CAST(:conversation_id AS uuid))))"
                        ),
                        "passthrough": "l.data->'passthrough'",
                        "feedback": (
                            "EXISTS (SELECT 1 FROM conversation_messages fm"
                            f" WHERE fm.id = {_LOG_MESSAGE_ID}"
                            " AND fm.feedback->>'text' = :feedback)"
                        ),
                        "label": _LOG_MESSAGE_ID,
                        "where": chat_where,
                        "sql": """
                        SELECT 'chat' AS event_type,
                               CAST(l.id AS text) AS id,
                               l.user_id AS user_id,
                               l.timestamp AS timestamp,
                               {level} AS level,
                               COALESCE(l.data->>'action', 'stream_answer') AS action,
                               {summary} AS summary,
                               l.data AS payload
                        FROM user_logs l
                        WHERE {where}
                        """,
                    },
                    {
                        # An answer still being written: a message row with
                        # no log row yet. It sits at its start time and gives
                        # way to the finished chat row.
                        "name": "chat_running",
                        "event_type": "chat",
                        "level": "'info'",
                        "summary": "m.prompt",
                        "ts": "m.timestamp",
                        "conversation": "m.conversation_id = CAST(:conversation_id AS uuid)",
                        "passthrough": "c.passthrough",
                        "where": running_chat_where + [
                            "m.status IN ('pending', 'streaming')",
                            "COALESCE((m.message_metadata ->> 'last_heartbeat_at')::timestamptz, m.timestamp)"
                            " > now() - make_interval(secs => :chat_fresh)",
                        ],
                        "sql": """
                        SELECT 'chat' AS event_type,
                               'run-' || CAST(m.id AS text) AS id,
                               m.user_id AS user_id,
                               m.timestamp AS timestamp,
                               {level} AS level,
                               'answer' AS action,
                               {summary} AS summary,
                               jsonb_build_object(
                                   'running', true,
                                   'status', m.status,
                                   'message_id', m.id,
                                   'conversation_id', m.conversation_id,
                                   'agent_id', c.agent_id,
                                   'passthrough', c.passthrough,
                                   'origin', CASE
                                       WHEN c.is_shared_usage THEN 'shared'
                                       WHEN c.visibility = 'listed' THEN 'chat'
                                       ELSE 'api' END
                               ) AS payload
                        FROM conversation_messages m
                        JOIN conversations c ON c.id = m.conversation_id
                        WHERE {where}
                        """,
                    },
                    {
                        "name": "system",
                        "level": "'error'",
                        "summary": "s.query",
                        "ts": "s.timestamp",
                        "where": system_where,
                        "sql": """
                        SELECT 'system' AS event_type,
                               CAST(s.id AS text) AS id,
                               s.user_id AS user_id,
                               s.timestamp AS timestamp,
                               {level} AS level,
                               COALESCE(s.endpoint, 'request') AS action,
                               {summary} AS summary,
                               jsonb_build_object(
                                   'endpoint', s.endpoint,
                                   'stacks', s.stacks,
                                   'activity_id', s.activity_id
                               ) AS payload
                        FROM stack_logs s
                        WHERE {where}
                        """,
                    },
                    {
                        "name": "webhook",
                        "level": "COALESCE(s.level, 'info')",
                        "summary": "s.query",
                        "ts": "s.timestamp",
                        "where": webhook_where,
                        "sql": """
                        SELECT 'webhook' AS event_type,
                               CAST(s.id AS text) AS id,
                               s.user_id AS user_id,
                               s.timestamp AS timestamp,
                               {level} AS level,
                               'webhook_run' AS action,
                               {summary} AS summary,
                               jsonb_build_object(
                                   'endpoint', s.endpoint,
                                   'stacks', s.stacks,
                                   'activity_id', s.activity_id
                               ) AS payload
                        FROM stack_logs s
                        WHERE {where}
                        """,
                    },
                    {
                        "name": "workflow",
                        "level": (
                            "CASE WHEN wr.status = 'failed' "
                            "THEN 'error' ELSE 'info' END"
                        ),
                        "summary": (
                            "COALESCE(wr.inputs->>'query', w.name, 'Workflow run')"
                        ),
                        "ts": "wr.started_at",
                        "where": workflow_where,
                        "sql": """
                        SELECT 'workflow' AS event_type,
                               CAST(wr.id AS text) AS id,
                               wr.user_id AS user_id,
                               wr.started_at AS timestamp,
                               {level} AS level,
                               'workflow_run' AS action,
                               {summary} AS summary,
                               jsonb_build_object(
                                   'status', wr.status,
                                   'workflow_name', w.name,
                                   'result', wr.result,
                                   'steps', wr.steps,
                                   'progress', wr.progress,
                                   'started_at', wr.started_at,
                                   'finished_at', wr.ended_at
                               ) AS payload
                        FROM workflow_runs wr
                        LEFT JOIN workflows w ON w.id = wr.workflow_id
                        WHERE {where}
                        """,
                    },
                    {
                        "name": "schedule",
                        "level": (
                            "CASE WHEN r.status IN ('failed', 'timeout') "
                            "THEN 'error' WHEN r.status = 'skipped' "
                            "THEN 'warning' ELSE 'info' END"
                        ),
                        "summary": (
                            "COALESCE(sc.name, sc.instruction, 'Scheduled run')"
                        ),
                        "ts": "COALESCE(r.started_at, r.scheduled_for)",
                        "conversation": "r.conversation_id = CAST(:conversation_id AS uuid)",
                        "where": schedule_where,
                        "sql": """
                        SELECT 'schedule' AS event_type,
                               CAST(r.id AS text) AS id,
                               r.user_id AS user_id,
                               COALESCE(r.started_at, r.scheduled_for) AS timestamp,
                               {level} AS level,
                               'scheduled_run' AS action,
                               {summary} AS summary,
                               jsonb_build_object(
                                   'status', r.status,
                                   'trigger_source', r.trigger_source,
                                   'schedule_name', sc.name,
                                   'instruction', sc.instruction,
                                   'output', r.output,
                                   'error', r.error,
                                   'error_type', r.error_type,
                                   'prompt_tokens', r.prompt_tokens,
                                   'generated_tokens', r.generated_tokens,
                                   'conversation_id', r.conversation_id,
                                   'scheduled_for', r.scheduled_for,
                                   'started_at', r.started_at,
                                   'finished_at', r.finished_at
                               ) AS payload
                        FROM schedule_runs r
                        LEFT JOIN schedules sc ON sc.id = r.schedule_id
                        WHERE {where}
                        """,
                    },
                    # Runs with no log row of their own are listed from their
                    # stored trace: searches (/api/search and MCP) and graph
                    # builds.
                    _trace_branch("search", "('search', 'mcp')", trace_scope),
                    _trace_branch("graph", "('graph_extraction')", trace_scope),
                ]

                params["chat_fresh"] = CHAT_FRESH_SECONDS
                if level:
                    params["level"] = level
                if search:
                    params["search"] = f"%{like_escape(search)}%"
                params["uuid_re"] = _UUID_RE
                for name in ("conversation_id", "feedback", "date_from", "date_to"):
                    if filters[name] is not None:
                        params[name] = filters[name]
                for index, (key, value) in enumerate(filters["passthrough"] or []):
                    params[f"pt_key_{index}"] = key
                    params[f"pt_value_{index}"] = value
                if filters["label"]:
                    params["schema_hash"] = analytics_schema.SCHEMA_HASH
                    params["label_min"] = settings.ANALYTICS_FILTER_MIN_PROBABILITY
                    params["label_name"] = filters["label"]

                branch_sqls = []
                for branch in branches:
                    if event_type and branch.get("event_type", branch["name"]) != event_type:
                        continue
                    # A row filter a branch has no column for leaves it out.
                    if (
                        (filters["conversation_id"] and "conversation" not in branch)
                        or (filters["passthrough"] and "passthrough" not in branch)
                        or (filters["feedback"] and "feedback" not in branch)
                        or (filters["label"] and "label" not in branch)
                    ):
                        continue
                    where = list(branch["where"])
                    if level:
                        where.append(f"{branch['level']} = :level")
                    if search:
                        where.append(
                            f"{branch['summary']} ILIKE :search ESCAPE '\\'"
                        )
                    if filters["conversation_id"]:
                        where.append(branch["conversation"])
                    for index in range(len(filters["passthrough"] or [])):
                        where.append(
                            f"{branch['passthrough']}->>CAST(:pt_key_{index} AS text) = :pt_value_{index}"
                        )
                    if filters["feedback"]:
                        where.append(branch["feedback"])
                    if filters["label"]:
                        where.append(log_label_exists(filters["label"], branch["label"]))
                    if filters["date_from"]:
                        where.append(f"{branch['ts']} >= :date_from")
                    if filters["date_to"]:
                        where.append(f"{branch['ts']} < :date_to")
                    branch_sqls.append(
                        branch["sql"].format(
                            level=branch["level"],
                            summary=branch["summary"],
                            where=" AND ".join(where),
                        )
                    )

                # ``ev.id`` is a unique per-branch tiebreaker: equal
                # timestamps (transaction-stable ``now()`` makes ties
                # routine) would otherwise sort non-deterministically
                # across page queries, duplicating a row on one page and
                # dropping its sibling from the next under OFFSET paging.
                sql = (
                    "SELECT * FROM ("
                    + " UNION ALL ".join(branch_sqls)
                    + ") ev ORDER BY ev.timestamp DESC, ev.id DESC"
                    " LIMIT :limit OFFSET :offset"
                )

                # A row filter no branch of the chosen type has (a label on
                # scheduled runs) matches nothing.
                rows = conn.execute(_sql_text(sql), params).fetchall() if branch_sqls else []

            has_more = len(rows) > page_size
            results = []
            for row in rows[:page_size]:
                m = row._mapping
                payload = m["payload"] or {}
                item = {
                    # Prefix with the source so ids stay unique across the
                    # merged tables (each has its own id sequence).
                    "id": f"{m['event_type']}-{m['id']}",
                    "event_type": m["event_type"],
                    "action": m["action"],
                    "level": m["level"],
                    "user": m["user_id"],
                    "question": m["summary"],
                    "timestamp": (
                        m["timestamp"].isoformat()
                        if hasattr(m["timestamp"], "isoformat")
                        else m["timestamp"]
                    ),
                }
                if payload.get("running"):
                    item.update(
                        {
                            "running": True,
                            "status": payload.get("status"),
                            "origin": payload.get("origin"),
                            "message_id": payload.get("message_id"),
                            "conversation_id": payload.get("conversation_id"),
                            "agent_id": payload.get("agent_id"),
                            "passthrough": payload.get("passthrough"),
                        }
                    )
                elif m["event_type"] == "chat":
                    item.update(
                        {
                            "response": payload.get("response"),
                            "sources": payload.get("sources"),
                            "tool_calls": payload.get("tool_calls"),
                            "agent_id": payload.get("agent_id"),
                            "attachments": payload.get("attachments"),
                            "request_id": payload.get("request_id"),
                            "message_id": payload.get("message_id"),
                            "conversation_id": payload.get("conversation_id"),
                            "passthrough": payload.get("passthrough"),
                            "error": payload.get("error"),
                        }
                    )
                elif m["event_type"] in ("system", "webhook"):
                    item.update(
                        {
                            "endpoint": payload.get("endpoint"),
                            # Redact on the way out too: rows written
                            # before write-time redaction still carry the
                            # reflected provider/user secrets in ``stacks``.
                            "stacks": redact_secrets(payload.get("stacks")),
                            "activity_id": payload.get("activity_id"),
                        }
                    )
                elif m["event_type"] in ("search", "graph"):
                    item.update(
                        {
                            "status": payload.get("status"),
                            "source": payload.get("source"),
                            "duration_ms": payload.get("duration_ms"),
                        }
                    )
                elif m["event_type"] == "workflow":
                    item.update(
                        {
                            "status": payload.get("status"),
                            "workflow_name": payload.get("workflow_name"),
                            "result": payload.get("result"),
                            "steps": payload.get("steps"),
                            "workflow_progress": payload.get("progress"),
                            "started_at": payload.get("started_at"),
                            "finished_at": payload.get("finished_at"),
                            "running": payload.get("status") == "running",
                        }
                    )
                else:  # schedule
                    item.update(
                        {
                            "status": payload.get("status"),
                            "trigger_source": payload.get("trigger_source"),
                            "schedule_name": payload.get("schedule_name"),
                            "instruction": payload.get("instruction"),
                            "output": payload.get("output"),
                            "error": payload.get("error"),
                            "error_type": payload.get("error_type"),
                            "prompt_tokens": payload.get("prompt_tokens"),
                            "generated_tokens": payload.get("generated_tokens"),
                            "conversation_id": payload.get("conversation_id"),
                            "scheduled_for": payload.get("scheduled_for"),
                            "started_at": payload.get("started_at") or payload.get("scheduled_for"),
                            "finished_at": payload.get("finished_at"),
                            "running": payload.get("status") in ("pending", "running"),
                        }
                    )
                if item.get("running"):
                    # A run sits at its start: the row's time, in the same
                    # format (JSON drops trailing zeros from the seconds).
                    item["started_at"] = item["timestamp"]
                results.append(item)
            row_filtered = any(
                filters[name]
                for name in ("conversation_id", "passthrough", "feedback", "label", "date_from", "date_to")
            )
            if (
                page == 1
                and event_type in (None, "webhook")
                and level in (None, "info")
                and not row_filtered
            ):
                # A webhook run has no row until it ends; its Redis marker
                # stands in for it on the first page.
                results = _merge_by_time(
                    results,
                    _running_webhook_rows(
                        params["user_id"], agent_pg_id if api_key_id else None, search
                    ),
                )
            tag_names: dict = {}
            if results:
                # Feedback, label and trace chips are extras: a failed lookup
                # must leave the page intact, just without them.
                try:
                    with db_readonly() as conn:
                        _attach_message_feedback(conn, results)
                except Exception:
                    current_app.logger.warning(
                        "Could not attach feedback to the logs page", exc_info=True
                    )
                try:
                    with db_readonly() as conn:
                        tag_names = _attach_labels(conn, results)
                except Exception:
                    current_app.logger.warning(
                        "Could not attach labels to the logs page", exc_info=True
                    )
                try:
                    with db_readonly() as conn:
                        _attach_trace_summaries(
                            conn,
                            results,
                            user_id=user,
                            agent_id=agent_pg_id if api_key_id else None,
                        )
                except Exception:
                    current_app.logger.warning(
                        "Could not attach trace summaries to the logs page",
                        exc_info=True,
                    )
        except AccessDenied as denied:
            return _denied(denied)
        except Exception as err:
            current_app.logger.error(
                f"Error getting user logs: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)

        return make_response(
            jsonify(
                {
                    "success": True,
                    "logs": results,
                    "page": page,
                    "page_size": page_size,
                    "has_more": has_more,
                    "tag_names": tag_names,
                }
            ),
            200,
        )
