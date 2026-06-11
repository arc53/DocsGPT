"""Analytics and reporting routes."""

import datetime

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from sqlalchemy import text as _sql_text

from application.api import api
from application.api.user.base import (
    generate_date_range,
    generate_hourly_range,
    generate_minute_range,
)
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.token_usage import TokenUsageRepository
from application.storage.db.session import db_readonly


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
    """Owner-scoped agent lookup for analytics filters.

    Returns ``(agent, api_key, agent_pg_id)``. ``api_key`` falls back to
    ``""`` and ``agent_pg_id`` to ``None``, neither of which matches any
    row, so filtering by an unknown (or another user's) agent returns
    nothing rather than everything. Accepts UUID or legacy Mongo
    ObjectId ids.
    """
    agent = (
        AgentsRepository(conn).get_any(api_key_id, user_id)
        if api_key_id
        else None
    )
    api_key = (agent or {}).get("key") or ""
    agent_pg_id = str(agent["id"]) if agent else None
    return agent, api_key, agent_pg_id


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
                _agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )

                # Count messages per bucket, filtered by the conversation's
                # owner (user_id) and optionally the agent. The ``user_id``
                # filter is always applied post-cutover to prevent
                # cross-tenant leakage on admin dashboards. Agent matching
                # covers both shapes: external traffic stamps ``api_key``,
                # owner chats stamp ``agent_id``.
                clauses = [
                    "c.user_id = :user_id",
                    "m.timestamp >= :start",
                    "m.timestamp <= :end",
                ]
                params: dict = {
                    "user_id": user,
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
        include_side_channel = bool(data.get("include_side_channel", True))

        window = _range_for_filter(filter_option)
        if window is None or group_by not in ("none", "model", "agent", "source"):
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, bucket_unit, _pg_fmt = window

        try:
            with db_readonly() as conn:
                _agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                # The owner-scoped lookup above gates access, so the
                # user_id filter is dropped when agent-filtering —
                # external API-key rows have no user_id.
                rows = TokenUsageRepository(conn).bucketed_totals(
                    bucket_unit=bucket_unit,
                    user_id=None if api_key_id else user,
                    api_key=api_key if api_key_id else None,
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
                _agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )

                # Feedback lives inside the ``conversation_messages.feedback``
                # JSONB as ``{"text": "like"|"dislike", "timestamp": "..."}``.
                # There is no scalar ``feedback_timestamp`` column — extract
                # the timestamp from the JSONB and cast it to timestamptz for
                # the range filter + bucket grouping.
                clauses = [
                    "c.user_id = :user_id",
                    "m.feedback IS NOT NULL",
                    "(m.feedback->>'timestamp')::timestamptz >= :start",
                    "(m.feedback->>'timestamp')::timestamptz <= :end",
                ]
                params: dict = {
                    "user_id": user,
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
                _agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )

                # Attribution: ``t.user_id`` is stamped at propose time
                # (0018); rows from before the migration fall back to the
                # parent message's user. Headless runs (scheduled / webhook)
                # have no message, so the message join is LEFT.
                clauses = [
                    "COALESCE(t.user_id, m.user_id) = :user_id",
                    "t.attempted_at >= :start",
                    "t.attempted_at <= :end",
                ]
                params: dict = {
                    "user_id": user,
                    "start": start_date,
                    "end": end_date,
                }
                join = (
                    "LEFT JOIN conversation_messages m ON m.id = t.message_id "
                    "LEFT JOIN conversations c ON c.id = m.conversation_id "
                )
                if api_key_id:
                    # Match by direct agent stamp (headless), by the
                    # conversation's api_key (external chat), or by the
                    # conversation's agent_id (owner chats / rows from
                    # before 0018 stamped attempts directly).
                    clauses.append(
                        "(t.agent_id = CAST(:agent_pg_id AS uuid)"
                        " OR c.api_key = :api_key"
                        " OR c.agent_id = CAST(:agent_pg_id AS uuid))"
                    )
                    params["agent_pg_id"] = agent_pg_id
                    params["api_key"] = api_key
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
                _agent, _api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )

                # A run's effective time is when it finished (fell back to
                # started/scheduled for runs that never got that far).
                ts = "COALESCE(r.finished_at, r.started_at, r.scheduled_for)"
                clauses = [
                    "r.user_id = :user_id",
                    f"{ts} >= :start",
                    f"{ts} <= :end",
                ]
                params: dict = {
                    "user_id": user,
                    "start": start_date,
                    "end": end_date,
                    "fmt": pg_fmt,
                }
                if api_key_id:
                    # Filtering by an agent that doesn't exist (or isn't
                    # the caller's) must return nothing, not everything.
                    clauses.append("r.agent_id = CAST(:agent_id AS uuid)")
                    params["agent_id"] = agent_pg_id
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
        except Exception as err:
            current_app.logger.error(
                f"Error getting schedule analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "runs": runs}), 200)


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
                enum=["chat", "schedule", "webhook", "workflow", "system"],
            ),
            "search": fields.String(
                required=False, description="Substring filter on the summary"
            ),
        },
    )

    @api.expect(get_user_logs_model)
    @api.doc(
        description=(
            "Get user activity logs with pagination. Merges chat answers "
            "(user_logs), request errors (stack_logs) and scheduled agent "
            "runs (schedule_runs) into one timeline."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        page = int(data.get("page", 1))
        api_key_id = data.get("api_key_id")
        page_size = int(data.get("page_size", 10))
        level = data.get("level")
        event_type = data.get("event_type")
        search = data.get("search")
        if level not in (None, "info", "error", "warning") or event_type not in (
            None,
            "chat",
            "schedule",
            "webhook",
            "workflow",
            "system",
        ):
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )

        try:
            with db_readonly() as conn:
                agent, api_key, agent_pg_id = _resolve_agent(
                    conn, api_key_id, user
                )
                params: dict = {
                    "user_id": user,
                    "limit": page_size + 1,
                    "offset": (page - 1) * page_size,
                }

                # ``schedule`` / ``webhook`` errors are first-class events in
                # their own branches; keep them out of ``system`` so a failed
                # run doesn't appear twice.
                chat_where = ["l.user_id = :user_id"]
                webhook_where = [
                    "s.user_id = :user_id",
                    "COALESCE(s.endpoint, '') = 'webhook'",
                ]
                system_where = [
                    "s.user_id = :user_id",
                    "s.level = 'error'",
                    "COALESCE(s.endpoint, '') NOT IN ('webhook', 'schedule')",
                ]
                # Terminal statuses only (worker writes ``success`` /
                # ``failed`` / ``timeout`` / ``skipped``; ``completed`` kept
                # defensively). Pending/running runs aren't log entries yet.
                schedule_where = [
                    "r.user_id = :user_id",
                    "r.status IN ('success', 'completed', 'failed', 'timeout', 'skipped')",
                ]
                workflow_where = ["wr.user_id = :user_id"]
                if api_key_id:
                    # Filter each source by the selected agent. An unknown
                    # agent (or one without a key) must match nothing. The
                    # agent lookup above is already owner-scoped, so the
                    # chat/webhook/system branches match on the agent key
                    # alone — shared agents log external callers under the
                    # caller's user_id, and the owner should still see that
                    # traffic on the agent's own logs page (legacy
                    # ``find_by_api_key`` behavior).
                    params["api_key"] = api_key
                    params["agent_pg_id"] = agent_pg_id
                    params["agent_workflow_id"] = (
                        str(agent["workflow_id"])
                        if agent and agent.get("workflow_id")
                        else None
                    )
                    chat_where = ["l.data->>'api_key' = :api_key"]
                    webhook_where = [
                        "COALESCE(s.endpoint, '') = 'webhook'",
                        "s.api_key = :api_key",
                    ]
                    system_where = [
                        "s.level = 'error'",
                        "COALESCE(s.endpoint, '') NOT IN ('webhook', 'schedule')",
                        "s.api_key = :api_key",
                    ]
                    schedule_where.append(
                        "r.agent_id = CAST(:agent_pg_id AS uuid)"
                    )
                    workflow_where.append(
                        "wr.workflow_id = CAST(:agent_workflow_id AS uuid)"
                    )

                # One normalized timeline over the three event sources.
                # ``payload`` carries the per-type detail; the outer query
                # paginates the merged, time-ordered result.
                sql = f"""
                    SELECT * FROM (
                        SELECT 'chat' AS event_type,
                               CAST(l.id AS text) AS id,
                               l.user_id AS user_id,
                               l.timestamp AS timestamp,
                               COALESCE(l.data->>'level', 'info') AS level,
                               COALESCE(l.data->>'action', 'stream_answer') AS action,
                               l.data->>'question' AS summary,
                               l.data AS payload
                        FROM user_logs l
                        WHERE {' AND '.join(chat_where)}
                        UNION ALL
                        SELECT 'system',
                               CAST(s.id AS text),
                               s.user_id,
                               s.timestamp,
                               COALESCE(s.level, 'error'),
                               COALESCE(s.endpoint, 'request'),
                               s.query,
                               jsonb_build_object(
                                   'endpoint', s.endpoint,
                                   'stacks', s.stacks
                               )
                        FROM stack_logs s
                        WHERE {' AND '.join(system_where)}
                        UNION ALL
                        SELECT 'webhook',
                               CAST(s.id AS text),
                               s.user_id,
                               s.timestamp,
                               COALESCE(s.level, 'info'),
                               'webhook_run',
                               s.query,
                               jsonb_build_object(
                                   'endpoint', s.endpoint,
                                   'stacks', s.stacks
                               )
                        FROM stack_logs s
                        WHERE {' AND '.join(webhook_where)}
                        UNION ALL
                        SELECT 'workflow',
                               CAST(wr.id AS text),
                               wr.user_id,
                               COALESCE(wr.ended_at, wr.started_at),
                               CASE
                                   WHEN wr.status = 'failed' THEN 'error'
                                   ELSE 'info'
                               END,
                               'workflow_run',
                               COALESCE(wr.inputs->>'query', w.name, 'Workflow run'),
                               jsonb_build_object(
                                   'status', wr.status,
                                   'workflow_name', w.name,
                                   'result', wr.result,
                                   'steps', wr.steps,
                                   'started_at', wr.started_at,
                                   'finished_at', wr.ended_at
                               )
                        FROM workflow_runs wr
                        LEFT JOIN workflows w ON w.id = wr.workflow_id
                        WHERE {' AND '.join(workflow_where)}
                        UNION ALL
                        SELECT 'schedule',
                               CAST(r.id AS text),
                               r.user_id,
                               COALESCE(r.finished_at, r.started_at, r.scheduled_for),
                               CASE
                                   WHEN r.status IN ('failed', 'timeout') THEN 'error'
                                   WHEN r.status = 'skipped' THEN 'warning'
                                   ELSE 'info'
                               END,
                               'scheduled_run',
                               COALESCE(sc.name, sc.instruction, 'Scheduled run'),
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
                               )
                        FROM schedule_runs r
                        LEFT JOIN schedules sc ON sc.id = r.schedule_id
                        WHERE {' AND '.join(schedule_where)}
                    ) ev
                """
                outer = []
                if level:
                    outer.append("ev.level = :level")
                    params["level"] = level
                if event_type:
                    outer.append("ev.event_type = :event_type")
                    params["event_type"] = event_type
                if search:
                    outer.append("ev.summary ILIKE :search ESCAPE '\\'")
                    escaped = (
                        search.replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                    )
                    params["search"] = f"%{escaped}%"
                if outer:
                    sql += " WHERE " + " AND ".join(outer)
                sql += " ORDER BY ev.timestamp DESC LIMIT :limit OFFSET :offset"

                rows = conn.execute(_sql_text(sql), params).fetchall()

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
                if m["event_type"] == "chat":
                    item.update(
                        {
                            "response": payload.get("response"),
                            "sources": payload.get("sources"),
                            "tool_calls": payload.get("tool_calls"),
                            "agent_id": payload.get("agent_id"),
                            "attachments": payload.get("attachments"),
                        }
                    )
                elif m["event_type"] in ("system", "webhook"):
                    item.update(
                        {
                            "endpoint": payload.get("endpoint"),
                            "stacks": payload.get("stacks"),
                        }
                    )
                elif m["event_type"] == "workflow":
                    item.update(
                        {
                            "status": payload.get("status"),
                            "workflow_name": payload.get("workflow_name"),
                            "result": payload.get("result"),
                            "steps": payload.get("steps"),
                            "started_at": payload.get("started_at"),
                            "finished_at": payload.get("finished_at"),
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
                            "started_at": payload.get("started_at"),
                            "finished_at": payload.get("finished_at"),
                        }
                    )
                results.append(item)
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
                }
            ),
            200,
        )
