import datetime
from unittest.mock import Mock, patch

import pytest
from bson import ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestGetMessageAnalytics:

    def test_returns_message_analytics_last_30_days(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = [
            {"_id": "2024-06-01", "count": 5},
            {"_id": "2024-06-02", "count": 3},
        ]
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={"filter_option": "last_30_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert "messages" in response.json

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        with app.test_request_context(
            "/api/get_message_analytics",
            method="POST",
            json={"filter_option": "last_30_days"},
        ):
            from flask import request

            request.decoded_token = None
            response = GetMessageAnalytics().post()

        assert response.status_code == 401

    def test_returns_400_invalid_filter_option(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={"filter_option": "invalid_option"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 400

    def test_filters_by_api_key(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        agent_id = ObjectId()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {
            "_id": agent_id,
            "key": "api_key_value",
        }
        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = []

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={
                    "filter_option": "last_7_days",
                    "api_key_id": str(agent_id),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 200
        pipeline = mock_conversations.aggregate.call_args[0][0]
        assert pipeline[0]["$match"].get("api_key") == "api_key_value"

    def test_last_hour_filter(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = []
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={"filter_option": "last_hour"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 200

    def test_last_24_hour_filter(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = []
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={"filter_option": "last_24_hour"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 200


@pytest.mark.unit
class TestGetTokenAnalytics:

    def test_returns_token_analytics(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        mock_token_usage = Mock()
        mock_token_usage.aggregate.return_value = [
            {"_id": {"day": "2024-06-01"}, "total_tokens": 1000}
        ]
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.token_usage_collection",
            mock_token_usage,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={"filter_option": "last_30_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert "token_usage" in response.json

    def test_returns_400_invalid_filter(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={"filter_option": "invalid"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestGetFeedbackAnalytics:

    def test_returns_feedback_analytics(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = [
            {"_id": "2024-06-01", "positive": 10, "negative": 2}
        ]
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_feedback_analytics",
                method="POST",
                json={"filter_option": "last_30_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetFeedbackAnalytics().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert "feedback" in response.json

    def test_returns_400_invalid_filter(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_feedback_analytics",
                method="POST",
                json={"filter_option": "bad"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetFeedbackAnalytics().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestGetUserLogs:

    def test_returns_paginated_logs(self, app):
        from application.api.user.analytics.routes import GetUserLogs

        log_id = ObjectId()
        mock_cursor = Mock()
        mock_cursor.sort.return_value.skip.return_value.limit.return_value = [
            {
                "_id": log_id,
                "action": "query",
                "level": "info",
                "user": "user1",
                "question": "test?",
                "sources": [],
                "retriever_params": {},
                "timestamp": datetime.datetime(2024, 6, 1),
            }
        ]
        mock_user_logs = Mock()
        mock_user_logs.find.return_value = mock_cursor
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.user_logs_collection",
            mock_user_logs,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_user_logs",
                method="POST",
                json={"page": 1, "page_size": 10},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetUserLogs().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["page"] == 1
        assert len(response.json["logs"]) == 1
        assert response.json["has_more"] is False

    def test_detects_has_more(self, app):
        from application.api.user.analytics.routes import GetUserLogs

        items = [
            {"_id": ObjectId(), "action": f"q{i}", "level": "info"}
            for i in range(3)
        ]
        mock_cursor = Mock()
        mock_cursor.sort.return_value.skip.return_value.limit.return_value = items
        mock_user_logs = Mock()
        mock_user_logs.find.return_value = mock_cursor
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.user_logs_collection",
            mock_user_logs,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_user_logs",
                method="POST",
                json={"page": 1, "page_size": 2},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetUserLogs().post()

        assert response.status_code == 200
        assert response.json["has_more"] is True
        assert len(response.json["logs"]) == 2

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetUserLogs

        with app.test_request_context(
            "/api/get_user_logs",
            method="POST",
            json={"page": 1},
        ):
            from flask import request

            request.decoded_token = None
            response = GetUserLogs().post()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetTokenAnalyticsAdditional:
    """Additional tests for GetTokenAnalytics covering missing lines."""

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        with app.test_request_context(
            "/api/get_token_analytics",
            method="POST",
            json={"filter_option": "last_30_days"},
        ):
            from flask import request

            request.decoded_token = None
            response = GetTokenAnalytics().post()

        assert response.status_code == 401

    def test_last_hour_filter(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        mock_token_usage = Mock()
        mock_token_usage.aggregate.return_value = [
            {"_id": {"minute": "2024-06-01 12:00:00"}, "total_tokens": 500}
        ]
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.token_usage_collection",
            mock_token_usage,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={"filter_option": "last_hour"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert "token_usage" in response.json

    def test_last_24_hour_filter(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        mock_token_usage = Mock()
        mock_token_usage.aggregate.return_value = [
            {"_id": {"hour": "2024-06-01 12:00"}, "total_tokens": 800}
        ]
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.token_usage_collection",
            mock_token_usage,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={"filter_option": "last_24_hour"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 200
        assert response.json["success"] is True

    def test_filters_by_api_key(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        agent_id = ObjectId()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {
            "_id": agent_id,
            "key": "token_api_key",
        }
        mock_token_usage = Mock()
        mock_token_usage.aggregate.return_value = []

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.analytics.routes.token_usage_collection",
            mock_token_usage,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={
                    "filter_option": "last_7_days",
                    "api_key_id": str(agent_id),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 200
        pipeline = mock_token_usage.aggregate.call_args[0][0]
        assert pipeline[0]["$match"].get("api_key") == "token_api_key"

    def test_api_key_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        mock_agents = Mock()
        mock_agents.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={
                    "filter_option": "last_30_days",
                    "api_key_id": str(ObjectId()),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 400

    def test_aggregate_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        mock_agents = Mock()
        mock_agents.find_one.return_value = None
        mock_token_usage = Mock()
        mock_token_usage.aggregate.side_effect = Exception("aggregate error")

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.analytics.routes.token_usage_collection",
            mock_token_usage,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={"filter_option": "last_30_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 400

    def test_last_15_days_filter(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        mock_token_usage = Mock()
        mock_token_usage.aggregate.return_value = []
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.token_usage_collection",
            mock_token_usage,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_token_analytics",
                method="POST",
                json={"filter_option": "last_15_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetTokenAnalytics().post()

        assert response.status_code == 200


@pytest.mark.unit
class TestGetFeedbackAnalyticsAdditional:
    """Additional tests for GetFeedbackAnalytics covering missing lines."""

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        with app.test_request_context(
            "/api/get_feedback_analytics",
            method="POST",
            json={"filter_option": "last_30_days"},
        ):
            from flask import request

            request.decoded_token = None
            response = GetFeedbackAnalytics().post()

        assert response.status_code == 401

    def test_last_hour_filter(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = []
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_feedback_analytics",
                method="POST",
                json={"filter_option": "last_hour"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetFeedbackAnalytics().post()

        assert response.status_code == 200

    def test_last_24_hour_filter(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = []
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_feedback_analytics",
                method="POST",
                json={"filter_option": "last_24_hour"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetFeedbackAnalytics().post()

        assert response.status_code == 200

    def test_filters_by_api_key(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        agent_id = ObjectId()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {
            "_id": agent_id,
            "key": "fb_api_key",
        }
        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = []

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/get_feedback_analytics",
                method="POST",
                json={
                    "filter_option": "last_7_days",
                    "api_key_id": str(agent_id),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetFeedbackAnalytics().post()

        assert response.status_code == 200
        pipeline = mock_conversations.aggregate.call_args[0][0]
        assert pipeline[0]["$match"].get("api_key") == "fb_api_key"

    def test_api_key_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        mock_agents = Mock()
        mock_agents.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_feedback_analytics",
                method="POST",
                json={
                    "filter_option": "last_30_days",
                    "api_key_id": str(ObjectId()),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetFeedbackAnalytics().post()

        assert response.status_code == 400

    def test_aggregate_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        mock_agents = Mock()
        mock_agents.find_one.return_value = None
        mock_conversations = Mock()
        mock_conversations.aggregate.side_effect = Exception("aggregate error")

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/get_feedback_analytics",
                method="POST",
                json={"filter_option": "last_30_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetFeedbackAnalytics().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestGetMessageAnalyticsAdditional:
    """Additional tests for GetMessageAnalytics covering error paths."""

    def test_api_key_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        mock_agents = Mock()
        mock_agents.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={
                    "filter_option": "last_30_days",
                    "api_key_id": str(ObjectId()),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 400

    def test_aggregate_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        mock_agents = Mock()
        mock_agents.find_one.return_value = None
        mock_conversations = Mock()
        mock_conversations.aggregate.side_effect = Exception("aggregate error")

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={"filter_option": "last_30_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 400

    def test_last_15_days_filter(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        mock_conversations = Mock()
        mock_conversations.aggregate.return_value = []
        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.analytics.routes.conversations_collection",
            mock_conversations,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_message_analytics",
                method="POST",
                json={"filter_option": "last_15_days"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetMessageAnalytics().post()

        assert response.status_code == 200


@pytest.mark.unit
class TestGetUserLogsAdditional:
    """Additional tests for GetUserLogs covering api_key filtering and errors."""

    def test_filters_by_api_key(self, app):
        from application.api.user.analytics.routes import GetUserLogs

        agent_id = ObjectId()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {
            "_id": agent_id,
            "key": "logs_api_key",
        }
        mock_cursor = Mock()
        mock_cursor.sort.return_value.skip.return_value.limit.return_value = []
        mock_user_logs = Mock()
        mock_user_logs.find.return_value = mock_cursor

        with patch(
            "application.api.user.analytics.routes.user_logs_collection",
            mock_user_logs,
        ), patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_user_logs",
                method="POST",
                json={
                    "page": 1,
                    "page_size": 10,
                    "api_key_id": str(agent_id),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetUserLogs().post()

        assert response.status_code == 200
        query_arg = mock_user_logs.find.call_args[0][0]
        assert query_arg == {"api_key": "logs_api_key"}

    def test_api_key_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetUserLogs

        mock_agents = Mock()
        mock_agents.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.analytics.routes.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/get_user_logs",
                method="POST",
                json={
                    "page": 1,
                    "api_key_id": str(ObjectId()),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetUserLogs().post()

        assert response.status_code == 400
