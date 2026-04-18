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
from application.storage.db.repositories.user_logs import UserLogsRepository
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


def _resolve_api_key(conn, api_key_id, user_id):
    """Look up the ``agents.key`` value for a given agent id.

    Scoped by ``user_id`` so an authenticated caller can't probe another
    user's agents. Accepts either UUID or legacy Mongo ObjectId shape.
    """
    if not api_key_id:
        return None
    agent = AgentsRepository(conn).get_any(api_key_id, user_id)
    return (agent or {}).get("key") if agent else None


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
                api_key = _resolve_api_key(conn, api_key_id, user)

                # Count messages per bucket, filtered by the conversation's
                # owner (user_id) and optionally the agent api_key. The
                # ``user_id`` filter is always applied post-cutover to
                # prevent cross-tenant leakage on admin dashboards.
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
                if api_key:
                    clauses.append("c.api_key = :api_key")
                    params["api_key"] = api_key
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

        window = _range_for_filter(filter_option)
        if window is None:
            return make_response(
                jsonify({"success": False, "message": "Invalid option"}), 400
            )
        start_date, end_date, bucket_unit, _pg_fmt = window

        try:
            with db_readonly() as conn:
                api_key = _resolve_api_key(conn, api_key_id, user)
                # ``bucketed_totals`` applies user_id / api_key filters
                # directly — no need to reshape a Mongo pipeline.
                rows = TokenUsageRepository(conn).bucketed_totals(
                    bucket_unit=bucket_unit,
                    user_id=user,
                    api_key=api_key,
                    timestamp_gte=start_date,
                    timestamp_lt=end_date,
                )

            intervals = _intervals_for_filter(filter_option, start_date, end_date)
            daily_token_usage = {interval: 0 for interval in intervals}
            for entry in rows:
                daily_token_usage[entry["bucket"]] = int(
                    entry["prompt_tokens"] + entry["generated_tokens"]
                )
        except Exception as err:
            current_app.logger.error(
                f"Error getting token analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "token_usage": daily_token_usage}), 200
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
                api_key = _resolve_api_key(conn, api_key_id, user)

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
                if api_key:
                    clauses.append("c.api_key = :api_key")
                    params["api_key"] = api_key
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
        },
    )

    @api.expect(get_user_logs_model)
    @api.doc(description="Get user logs with pagination")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        page = int(data.get("page", 1))
        api_key_id = data.get("api_key_id")
        page_size = int(data.get("page_size", 10))

        try:
            with db_readonly() as conn:
                api_key = _resolve_api_key(conn, api_key_id, user)
                logs_repo = UserLogsRepository(conn)
                if api_key:
                    # ``find_by_api_key`` filters on ``data->>'api_key'``
                    # — the PG shape of the legacy top-level ``api_key``
                    # filter. Paginate client-side using offset/limit.
                    all_rows = logs_repo.find_by_api_key(api_key)
                    offset = (page - 1) * page_size
                    window = all_rows[offset: offset + page_size + 1]
                    items = window
                else:
                    items, has_more_flag = logs_repo.list_paginated(
                        user_id=user,
                        page=page,
                        page_size=page_size,
                    )
                    # list_paginated already trims to page_size and
                    # returns has_more separately.
                    results = [
                        {
                            "id": str(item.get("id") or item.get("_id")),
                            "action": (item.get("data") or {}).get("action"),
                            "level": (item.get("data") or {}).get("level"),
                            "user": item.get("user_id"),
                            "question": (item.get("data") or {}).get("question"),
                            "sources": (item.get("data") or {}).get("sources"),
                            "retriever_params": (item.get("data") or {}).get(
                                "retriever_params"
                            ),
                            "timestamp": (
                                item["timestamp"].isoformat()
                                if hasattr(item.get("timestamp"), "isoformat")
                                else item.get("timestamp")
                            ),
                        }
                        for item in items
                    ]
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "logs": results,
                                "page": page,
                                "page_size": page_size,
                                "has_more": has_more_flag,
                            }
                        ),
                        200,
                    )

            has_more = len(items) > page_size
            items = items[:page_size]
            results = [
                {
                    "id": str(item.get("id") or item.get("_id")),
                    "action": (item.get("data") or {}).get("action"),
                    "level": (item.get("data") or {}).get("level"),
                    "user": item.get("user_id"),
                    "question": (item.get("data") or {}).get("question"),
                    "sources": (item.get("data") or {}).get("sources"),
                    "retriever_params": (item.get("data") or {}).get(
                        "retriever_params"
                    ),
                    "timestamp": (
                        item["timestamp"].isoformat()
                        if hasattr(item.get("timestamp"), "isoformat")
                        else item.get("timestamp")
                    ),
                }
                for item in items
            ]
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
