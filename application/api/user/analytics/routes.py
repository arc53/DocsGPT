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

    Returns ``(agent, api_key, agent_pg_id)``. ``agent`` is ``None`` when
    the id doesn't resolve to one of the caller's agents — callers must
    short-circuit with an empty result, not fall back to sentinel filter
    values. ``api_key`` is ``None`` (never ``""``) for key-less agents:
    draft agents store ``key = ''``, and an ``''`` filter would match the
    ``''`` that writers like ``stack_logs`` stamp on every key-less
    request — leaking rows across users. NULL matches nothing. Accepts
    UUID or legacy Mongo ObjectId ids.
    """
    agent = (
        AgentsRepository(conn).get_any(api_key_id, user_id)
        if api_key_id
        else None
    )
    api_key = (agent or {}).get("key") or None
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
        try:
            page = max(1, int(data.get("page") or 1))
            page_size = max(1, min(100, int(data.get("page_size") or 10)))
        except (TypeError, ValueError):
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        api_key_id = data.get("api_key_id")
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
                            }
                        ),
                        200,
                    )
                params: dict = {
                    "user_id": user,
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
                    webhook_where = [
                        "COALESCE(s.endpoint, '') = 'webhook'",
                        "s.api_key = :api_key",
                        webhook_dedupe,
                    ]
                    system_where = [
                        "s.level = 'error'",
                        "COALESCE(s.endpoint, '') NOT IN ('webhook', 'schedule')",
                        "s.api_key = :api_key",
                    ]
                    # Owner-gated agent match: drop the user clause so a
                    # shared agent's runs (stamped with the caller's
                    # user_id by the scheduler tool) appear on the owner's
                    # per-agent timeline, consistent with the chat branch.
                    schedule_where = [
                        "r.status IN ('success', 'completed', 'failed', 'timeout', 'skipped')",
                        "r.agent_id = CAST(:agent_pg_id AS uuid)",
                    ]
                    workflow_where = [
                        "wr.user_id = :user_id",
                        "wr.workflow_id = CAST(:agent_workflow_id AS uuid)",
                    ]
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
                    ]
                    # Terminal statuses only (worker writes ``success`` /
                    # ``failed`` / ``timeout`` / ``skipped``; ``completed``
                    # kept defensively). Pending/running runs aren't log
                    # entries yet.
                    schedule_where = [
                        "r.user_id = :user_id",
                        "r.status IN ('success', 'completed', 'failed', 'timeout', 'skipped')",
                    ]
                    workflow_where = ["wr.user_id = :user_id"]

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
                        "name": "system",
                        "level": "'error'",
                        "summary": "s.query",
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
                                   'stacks', s.stacks
                               ) AS payload
                        FROM stack_logs s
                        WHERE {where}
                        """,
                    },
                    {
                        "name": "webhook",
                        "level": "COALESCE(s.level, 'info')",
                        "summary": "s.query",
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
                                   'stacks', s.stacks
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
                        "where": workflow_where,
                        "sql": """
                        SELECT 'workflow' AS event_type,
                               CAST(wr.id AS text) AS id,
                               wr.user_id AS user_id,
                               COALESCE(wr.ended_at, wr.started_at) AS timestamp,
                               {level} AS level,
                               'workflow_run' AS action,
                               {summary} AS summary,
                               jsonb_build_object(
                                   'status', wr.status,
                                   'workflow_name', w.name,
                                   'result', wr.result,
                                   'steps', wr.steps,
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
                        "where": schedule_where,
                        "sql": """
                        SELECT 'schedule' AS event_type,
                               CAST(r.id AS text) AS id,
                               r.user_id AS user_id,
                               COALESCE(r.finished_at, r.started_at, r.scheduled_for) AS timestamp,
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
                ]

                if level:
                    params["level"] = level
                if search:
                    escaped = (
                        search.replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                    )
                    params["search"] = f"%{escaped}%"

                branch_sqls = []
                for branch in branches:
                    if event_type and branch["name"] != event_type:
                        continue
                    where = list(branch["where"])
                    if level:
                        where.append(f"{branch['level']} = :level")
                    if search:
                        where.append(
                            f"{branch['summary']} ILIKE :search ESCAPE '\\'"
                        )
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
