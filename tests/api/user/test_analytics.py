"""Tests for application/api/user/analytics/routes.py.

Uses the ephemeral ``pg_conn`` fixture so analytics SQL runs against a real
(in-memory) Postgres schema.
"""

import datetime
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_analytics_db(conn):
    @contextmanager
    def _yield_conn():
        yield conn

    with patch(
        "application.api.user.analytics.routes.db_readonly", _yield_conn
    ):
        yield


def _seed_conversation_with_messages(
    pg_conn, user_id, *, count=3, api_key=None, feedback_text=None,
):
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )
    repo = ConversationsRepository(pg_conn)
    conv = repo.create(user_id, name="t", api_key=api_key)
    conv_id = str(conv["id"])
    for i in range(count):
        repo.append_message(conv_id, {"prompt": f"p{i}", "response": f"r{i}"})
        if feedback_text is not None:
            repo.set_feedback(
                conv_id,
                i,
                {
                    "text": feedback_text if i % 2 == 0 else "dislike",
                    "timestamp": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                },
            )
    return conv_id


class TestRangeForFilter:
    def test_returns_none_for_invalid_filter(self):
        from application.api.user.analytics.routes import _range_for_filter

        assert _range_for_filter("bogus") is None

    @pytest.mark.parametrize(
        "option",
        ["last_hour", "last_24_hour", "last_7_days", "last_15_days", "last_30_days"],
    )
    def test_returns_start_end_for_supported(self, option):
        from application.api.user.analytics.routes import _range_for_filter

        got = _range_for_filter(option)
        assert got is not None
        start, end, bucket_unit, pg_fmt = got
        assert start < end
        assert bucket_unit in {"minute", "hour", "day"}


class TestResolveApiKey:
    def test_none_when_no_id(self, pg_conn):
        from application.api.user.analytics.routes import _resolve_api_key

        assert _resolve_api_key(pg_conn, None, "u") is None
        assert _resolve_api_key(pg_conn, "", "u") is None

    def test_returns_key_for_owned_agent(self, pg_conn):
        from application.api.user.analytics.routes import _resolve_api_key
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "test-agent", "published", key="secret-api-key",
        )
        assert (
            _resolve_api_key(pg_conn, str(agent["id"]), "owner")
            == "secret-api-key"
        )

    def test_none_for_other_users_agent(self, pg_conn):
        from application.api.user.analytics.routes import _resolve_api_key
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "test-agent", "published", key="secret"
        )
        assert _resolve_api_key(pg_conn, str(agent["id"]), "other-user") is None


class TestGetMessageAnalytics:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        with app.test_request_context(
            "/api/get_message_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetMessageAnalytics().post()
        assert response.status_code == 401

    def test_invalid_filter_returns_400(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        with app.test_request_context(
            "/api/get_message_analytics",
            method="POST",
            json={"filter_option": "nope"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetMessageAnalytics().post()
        assert response.status_code == 400

    def test_returns_bucketed_counts(self, app, pg_conn):
        from application.api.user.analytics.routes import GetMessageAnalytics

        user = "u-msg"
        _seed_conversation_with_messages(pg_conn, user, count=3)

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_message_analytics",
            method="POST",
            json={"filter_option": "last_30_days"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetMessageAnalytics().post()
        assert response.status_code == 200
        assert response.json["success"] is True
        messages = response.json["messages"]
        assert isinstance(messages, dict)
        assert sum(messages.values()) == 3

    def test_filters_by_api_key(self, app, pg_conn):
        from application.api.user.analytics.routes import GetMessageAnalytics
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-msg-key"
        agent = AgentsRepository(pg_conn).create(
            user, "a", "published", key="k1",
        )
        _seed_conversation_with_messages(pg_conn, user, count=4, api_key="k1")
        _seed_conversation_with_messages(pg_conn, user, count=2)

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_message_analytics",
            method="POST",
            json={"api_key_id": str(agent["id"]), "filter_option": "last_30_days"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetMessageAnalytics().post()
        assert response.status_code == 200
        assert sum(response.json["messages"].values()) == 4

    def test_db_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetMessageAnalytics

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/get_message_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetMessageAnalytics().post()
        assert response.status_code == 400


class TestGetTokenAnalytics:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        with app.test_request_context(
            "/api/get_token_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetTokenAnalytics().post()
        assert response.status_code == 401

    def test_invalid_filter_returns_400(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        with app.test_request_context(
            "/api/get_token_analytics",
            method="POST",
            json={"filter_option": "bogus"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetTokenAnalytics().post()
        assert response.status_code == 400

    def test_returns_token_usage_shape(self, app, pg_conn):
        from application.api.user.analytics.routes import GetTokenAnalytics

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_token_analytics",
            method="POST",
            json={"filter_option": "last_30_days"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-token"}
            response = GetTokenAnalytics().post()
        assert response.status_code == 200
        assert response.json["success"] is True
        assert isinstance(response.json["token_usage"], dict)

    def test_db_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetTokenAnalytics

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/get_token_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetTokenAnalytics().post()
        assert response.status_code == 400


class TestGetFeedbackAnalytics:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        with app.test_request_context(
            "/api/get_feedback_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetFeedbackAnalytics().post()
        assert response.status_code == 401

    def test_invalid_filter_returns_400(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        with app.test_request_context(
            "/api/get_feedback_analytics",
            method="POST",
            json={"filter_option": "nope"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetFeedbackAnalytics().post()
        assert response.status_code == 400

    def test_returns_positive_and_negative_counts(self, app, pg_conn):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        user = "u-fb"
        _seed_conversation_with_messages(
            pg_conn, user, count=4, feedback_text="like",
        )

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_feedback_analytics",
            method="POST",
            json={"filter_option": "last_30_days"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetFeedbackAnalytics().post()
        assert response.status_code == 200
        fb = response.json["feedback"]
        total_pos = sum(b["positive"] for b in fb.values())
        total_neg = sum(b["negative"] for b in fb.values())
        assert total_pos == 2
        assert total_neg == 2

    def test_db_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/get_feedback_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetFeedbackAnalytics().post()
        assert response.status_code == 400


class TestGetUserLogs:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.analytics.routes import GetUserLogs

        with app.test_request_context(
            "/api/get_user_logs", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetUserLogs().post()
        assert response.status_code == 401

    def test_returns_logs_list_paginated(self, app, pg_conn):
        from application.api.user.analytics.routes import GetUserLogs
        from application.storage.db.repositories.user_logs import (
            UserLogsRepository,
        )

        user = "u-logs"
        logs_repo = UserLogsRepository(pg_conn)
        for i in range(3):
            logs_repo.insert(
                user_id=user,
                endpoint="info",
                data={"action": "chat", "question": f"q{i}"},
            )

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_user_logs",
            method="POST",
            json={"page": 1, "page_size": 10},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetUserLogs().post()
        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert len(data["logs"]) == 3
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_filters_logs_by_api_key(self, app, pg_conn):
        from application.api.user.analytics.routes import GetUserLogs
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.user_logs import (
            UserLogsRepository,
        )

        user = "u-logs-key"
        agent = AgentsRepository(pg_conn).create(
            user, "a", "published", key="myk",
        )
        logs_repo = UserLogsRepository(pg_conn)
        logs_repo.insert(
            user_id=user, endpoint="info",
            data={"action": "a", "api_key": "myk"},
        )
        logs_repo.insert(
            user_id=user, endpoint="info",
            data={"action": "a", "api_key": "other"},
        )

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_user_logs",
            method="POST",
            json={"api_key_id": str(agent["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetUserLogs().post()
        assert response.status_code == 200
        assert len(response.json["logs"]) == 1

    def test_db_error_returns_400(self, app):
        from application.api.user.analytics.routes import GetUserLogs

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/get_user_logs", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetUserLogs().post()
        assert response.status_code == 400
