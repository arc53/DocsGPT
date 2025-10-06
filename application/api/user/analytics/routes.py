"""Analytics and reporting routes."""

import datetime

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import (
    agents_collection,
    conversations_collection,
    generate_date_range,
    generate_hourly_range,
    generate_minute_range,
    token_usage_collection,
    user_logs_collection,
)

analytics_ns = Namespace(
    "analytics", description="Analytics and reporting operations", path="/api"
)


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
                enum=[
                    "last_hour",
                    "last_24_hour",
                    "last_7_days",
                    "last_15_days",
                    "last_30_days",
                ],
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
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id), "user": user})[
                    "key"
                ]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
        else:
            if filter_option in ["last_7_days", "last_15_days", "last_30_days"]:
                filter_days = (
                    6
                    if filter_option == "last_7_days"
                    else 14 if filter_option == "last_15_days" else 29
                )
            else:
                return make_response(
                    jsonify({"success": False, "message": "Invalid option"}), 400
                )
            start_date = end_date - datetime.timedelta(days=filter_days)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            group_format = "%Y-%m-%d"
        try:
            match_stage = {
                "$match": {
                    "user": user,
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key
            pipeline = [
                match_stage,
                {"$unwind": "$queries"},
                {
                    "$match": {
                        "queries.timestamp": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$queries.timestamp",
                            }
                        },
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"_id": 1}},
            ]

            message_data = conversations_collection.aggregate(pipeline)

            if filter_option == "last_hour":
                intervals = generate_minute_range(start_date, end_date)
            elif filter_option == "last_24_hour":
                intervals = generate_hourly_range(start_date, end_date)
            else:
                intervals = generate_date_range(start_date, end_date)
            daily_messages = {interval: 0 for interval in intervals}

            for entry in message_data:
                daily_messages[entry["_id"]] = entry["count"]
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
                enum=[
                    "last_hour",
                    "last_24_hour",
                    "last_7_days",
                    "last_15_days",
                    "last_30_days",
                ],
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
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id), "user": user})[
                    "key"
                ]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
            group_stage = {
                "$group": {
                    "_id": {
                        "minute": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        }
                    },
                    "total_tokens": {
                        "$sum": {"$add": ["$prompt_tokens", "$generated_tokens"]}
                    },
                }
            }
        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
            group_stage = {
                "$group": {
                    "_id": {
                        "hour": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        }
                    },
                    "total_tokens": {
                        "$sum": {"$add": ["$prompt_tokens", "$generated_tokens"]}
                    },
                }
            }
        else:
            if filter_option in ["last_7_days", "last_15_days", "last_30_days"]:
                filter_days = (
                    6
                    if filter_option == "last_7_days"
                    else (14 if filter_option == "last_15_days" else 29)
                )
            else:
                return make_response(
                    jsonify({"success": False, "message": "Invalid option"}), 400
                )
            start_date = end_date - datetime.timedelta(days=filter_days)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            group_format = "%Y-%m-%d"
            group_stage = {
                "$group": {
                    "_id": {
                        "day": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        }
                    },
                    "total_tokens": {
                        "$sum": {"$add": ["$prompt_tokens", "$generated_tokens"]}
                    },
                }
            }
        try:
            match_stage = {
                "$match": {
                    "user_id": user,
                    "timestamp": {"$gte": start_date, "$lte": end_date},
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key
            token_usage_data = token_usage_collection.aggregate(
                [
                    match_stage,
                    group_stage,
                    {"$sort": {"_id": 1}},
                ]
            )

            if filter_option == "last_hour":
                intervals = generate_minute_range(start_date, end_date)
            elif filter_option == "last_24_hour":
                intervals = generate_hourly_range(start_date, end_date)
            else:
                intervals = generate_date_range(start_date, end_date)
            daily_token_usage = {interval: 0 for interval in intervals}

            for entry in token_usage_data:
                if filter_option == "last_hour":
                    daily_token_usage[entry["_id"]["minute"]] = entry["total_tokens"]
                elif filter_option == "last_24_hour":
                    daily_token_usage[entry["_id"]["hour"]] = entry["total_tokens"]
                else:
                    daily_token_usage[entry["_id"]["day"]] = entry["total_tokens"]
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
                enum=[
                    "last_hour",
                    "last_24_hour",
                    "last_7_days",
                    "last_15_days",
                    "last_30_days",
                ],
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
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id), "user": user})[
                    "key"
                ]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
            date_field = {
                "$dateToString": {
                    "format": group_format,
                    "date": "$queries.feedback_timestamp",
                }
            }
        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
            date_field = {
                "$dateToString": {
                    "format": group_format,
                    "date": "$queries.feedback_timestamp",
                }
            }
        else:
            if filter_option in ["last_7_days", "last_15_days", "last_30_days"]:
                filter_days = (
                    6
                    if filter_option == "last_7_days"
                    else (14 if filter_option == "last_15_days" else 29)
                )
            else:
                return make_response(
                    jsonify({"success": False, "message": "Invalid option"}), 400
                )
            start_date = end_date - datetime.timedelta(days=filter_days)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            group_format = "%Y-%m-%d"
            date_field = {
                "$dateToString": {
                    "format": group_format,
                    "date": "$queries.feedback_timestamp",
                }
            }
        try:
            match_stage = {
                "$match": {
                    "queries.feedback_timestamp": {
                        "$gte": start_date,
                        "$lte": end_date,
                    },
                    "queries.feedback": {"$exists": True},
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key
            pipeline = [
                match_stage,
                {"$unwind": "$queries"},
                {"$match": {"queries.feedback": {"$exists": True}}},
                {
                    "$group": {
                        "_id": {"time": date_field, "feedback": "$queries.feedback"},
                        "count": {"$sum": 1},
                    }
                },
                {
                    "$group": {
                        "_id": "$_id.time",
                        "positive": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$_id.feedback", "LIKE"]},
                                    "$count",
                                    0,
                                ]
                            }
                        },
                        "negative": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$_id.feedback", "DISLIKE"]},
                                    "$count",
                                    0,
                                ]
                            }
                        },
                    }
                },
                {"$sort": {"_id": 1}},
            ]

            feedback_data = conversations_collection.aggregate(pipeline)

            if filter_option == "last_hour":
                intervals = generate_minute_range(start_date, end_date)
            elif filter_option == "last_24_hour":
                intervals = generate_hourly_range(start_date, end_date)
            else:
                intervals = generate_date_range(start_date, end_date)
            daily_feedback = {
                interval: {"positive": 0, "negative": 0} for interval in intervals
            }

            for entry in feedback_data:
                daily_feedback[entry["_id"]] = {
                    "positive": entry["positive"],
                    "negative": entry["negative"],
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
        data = request.get_json()
        page = int(data.get("page", 1))
        api_key_id = data.get("api_key_id")
        page_size = int(data.get("page_size", 10))
        skip = (page - 1) * page_size

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id)})["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        query = {"user": user}
        if api_key:
            query = {"api_key": api_key}
        items_cursor = (
            user_logs_collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(page_size + 1)
        )
        items = list(items_cursor)

        results = [
            {
                "id": str(item.get("_id")),
                "action": item.get("action"),
                "level": item.get("level"),
                "user": item.get("user"),
                "question": item.get("question"),
                "sources": item.get("sources"),
                "retriever_params": item.get("retriever_params"),
                "timestamp": item.get("timestamp"),
            }
            for item in items[:page_size]
        ]

        has_more = len(items) > page_size

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
