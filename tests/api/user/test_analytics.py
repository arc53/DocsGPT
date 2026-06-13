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
    agent_id=None,
):
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )
    repo = ConversationsRepository(pg_conn)
    conv = repo.create(user_id, name="t", api_key=api_key, agent_id=agent_id)
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


class TestResolveAgent:
    def test_no_agent_when_no_id(self, pg_conn):
        from application.api.user.analytics.routes import _resolve_agent

        assert _resolve_agent(pg_conn, None, "u") == (None, None, None)
        assert _resolve_agent(pg_conn, "", "u") == (None, None, None)

    def test_returns_key_and_id_for_owned_agent(self, pg_conn):
        from application.api.user.analytics.routes import _resolve_agent
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "test-agent", "published", key="secret-api-key",
        )
        resolved, api_key, agent_pg_id = _resolve_agent(
            pg_conn, str(agent["id"]), "owner"
        )
        assert resolved is not None
        assert api_key == "secret-api-key"
        assert agent_pg_id == str(agent["id"])

    def test_keyless_agent_yields_none_key(self, pg_conn):
        from application.api.user.analytics.routes import _resolve_agent
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "test-agent", "draft", key="",
        )
        resolved, api_key, agent_pg_id = _resolve_agent(
            pg_conn, str(agent["id"]), "owner"
        )
        # Draft agents store key=''; the resolved api_key must be None
        # so the filter can't match key-less rows across users (see
        # _resolve_agent). agent_id still matches the agent's rows.
        assert resolved is not None
        assert api_key is None
        assert agent_pg_id == str(agent["id"])

    def test_no_match_for_other_users_agent(self, pg_conn):
        from application.api.user.analytics.routes import _resolve_agent
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "owner", "test-agent", "published", key="secret"
        )
        assert _resolve_agent(pg_conn, str(agent["id"]), "other-user") == (
            None,
            None,
            None,
        )


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


def _seed_stack_log(
    pg_conn, *, user_id, api_key="", level="error",
    endpoint="stream", query="secret prompt", activity_id=None,
):
    import uuid as _uuid

    from application.storage.db.repositories.stack_logs import (
        StackLogsRepository,
    )

    StackLogsRepository(pg_conn).insert(
        activity_id=activity_id or str(_uuid.uuid4()),
        endpoint=endpoint,
        level=level,
        user_id=user_id,
        api_key=api_key,
        query=query,
        stacks=[{"component": "error", "data": {"message": "boom"}}],
    )


def _post_logs(app, pg_conn, user, body):
    from application.api.user.analytics.routes import GetUserLogs

    with _patch_analytics_db(pg_conn), app.test_request_context(
        "/api/get_user_logs", method="POST", json=body
    ):
        from flask import request
        request.decoded_token = {"sub": user}
        return GetUserLogs().post()


class TestCrossTenantIsolation:
    """Pinned regression for the '' api_key sentinel leak.

    Every normal (non-API-key) request's stack_logs rows store
    api_key='' (logging.py defaults the missing attribute to ""). An
    agent filter that resolved to an '' sentinel and dropped the
    user_id clause therefore matched EVERY tenant's error logs.
    """

    def test_bogus_agent_id_leaks_nothing(self, app, pg_conn):
        import uuid as _uuid

        _seed_stack_log(pg_conn, user_id="victim", api_key="")

        response = _post_logs(
            app,
            pg_conn,
            "attacker",
            {"api_key_id": str(_uuid.uuid4()), "event_type": "system"},
        )
        assert response.status_code == 200
        assert response.json["logs"] == []
        assert response.json["has_more"] is False

    def test_own_draft_agent_leaks_nothing(self, app, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        _seed_stack_log(pg_conn, user_id="victim", api_key="")
        # Draft agents legitimately store key='' — filtering by one must
        # not match other tenants' key-less ('') stack_logs rows.
        draft = AgentsRepository(pg_conn).create(
            "attacker", "draft-agent", "draft", key="",
        )

        response = _post_logs(
            app,
            pg_conn,
            "attacker",
            {"api_key_id": str(draft["id"]), "event_type": "system"},
        )
        assert response.status_code == 200
        assert response.json["logs"] == []

    def test_other_users_agent_id_returns_empty_tokens(self, app, pg_conn):
        from application.api.user.analytics.routes import GetTokenAnalytics
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.token_usage import (
            TokenUsageRepository,
        )

        b_agent = AgentsRepository(pg_conn).create(
            "user-b", "b-agent", "published", key="b-key",
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="user-b", api_key="b-key", prompt_tokens=777,
            generated_tokens=333,
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="user-a", prompt_tokens=10, generated_tokens=5,
        )

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_token_analytics",
            method="POST",
            json={"api_key_id": str(b_agent["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": "user-a"}
            response = GetTokenAnalytics().post()
        assert response.status_code == 200
        # Unresolved filter == explicit empty, not "fall back to my data".
        assert sum(response.json["token_usage"].values()) == 0


class TestGetToolAnalytics:
    def _post(self, app, pg_conn, user, body):
        from application.api.user.analytics.routes import GetToolAnalytics

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_tool_analytics", method="POST", json=body
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return GetToolAnalytics().post()

    def test_counts_terminal_attempts_only(self, app, pg_conn):
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("c1", "brave", "search", {}, user_id="u-tools")
        repo.mark_executed("c1", "ok")
        repo.record_proposed("c2", "brave", "search", {}, user_id="u-tools")
        repo.mark_failed("c2", "boom")
        # Stuck proposed row: neither success nor failure — must not
        # count as a phantom success.
        repo.record_proposed("c3", "brave", "search", {}, user_id="u-tools")
        # Another user's attempt is invisible.
        repo.record_proposed("c4", "brave", "search", {}, user_id="someone")
        repo.mark_executed("c4", "ok")

        response = self._post(app, pg_conn, "u-tools", {})
        assert response.status_code == 200
        tools = {t["tool_name"]: t for t in response.json["tools"]}
        assert tools["brave"]["calls"] == 2
        assert tools["brave"]["failures"] == 1

    def test_unknown_agent_returns_empty(self, app, pg_conn):
        import uuid as _uuid

        response = self._post(
            app, pg_conn, "u-tools", {"api_key_id": str(_uuid.uuid4())}
        )
        assert response.status_code == 200
        assert response.json["tools"] == []

    def test_filters_by_agent_stamp(self, app, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        agent = AgentsRepository(pg_conn).create(
            "u-tools", "a", "published", key="tk",
        )
        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed(
            "c10", "ntfy", "send", {},
            user_id="u-tools", agent_id=str(agent["id"]),
        )
        repo.mark_executed("c10", "ok")
        repo.record_proposed("c11", "brave", "search", {}, user_id="u-tools")
        repo.mark_executed("c11", "ok")

        response = self._post(
            app, pg_conn, "u-tools", {"api_key_id": str(agent["id"])}
        )
        assert response.status_code == 200
        names = [t["tool_name"] for t in response.json["tools"]]
        assert names == ["ntfy"]


class TestGetScheduleAnalytics:
    def _seed_run(self, pg_conn, user, status, *, agent_id=None):
        import datetime as _dt

        from application.storage.db.repositories.schedule_runs import (
            ScheduleRunsRepository,
        )
        from application.storage.db.repositories.schedules import (
            SchedulesRepository,
        )

        now = _dt.datetime.now(_dt.timezone.utc)
        # The schedules_once_run_at_chk constraint requires run_at on
        # once-type schedules.
        schedule = SchedulesRepository(pg_conn).create(
            user, agent_id, "once", "do the thing", run_at=now,
        )
        run = ScheduleRunsRepository(pg_conn).record_pending(
            str(schedule["id"]), user, agent_id, now,
        )
        ScheduleRunsRepository(pg_conn).update(
            str(run["id"]),
            {"status": status, "started_at": now, "finished_at": now},
        )
        return schedule

    def _post(self, app, pg_conn, user, body):
        from application.api.user.analytics.routes import GetScheduleAnalytics

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_schedule_analytics", method="POST", json=body
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return GetScheduleAnalytics().post()

    def test_maps_worker_statuses(self, app, pg_conn):
        user = "u-sched"
        self._seed_run(pg_conn, user, "success")
        self._seed_run(pg_conn, user, "failed")
        self._seed_run(pg_conn, user, "timeout")
        self._seed_run(pg_conn, user, "skipped")

        response = self._post(app, pg_conn, user, {})
        assert response.status_code == 200
        totals = {"completed": 0, "failed": 0, "skipped": 0}
        for bucket in response.json["runs"].values():
            for key in totals:
                totals[key] += bucket[key]
        # success → completed; failed + timeout → failed; skipped → skipped.
        assert totals == {"completed": 1, "failed": 2, "skipped": 1}

    def test_unknown_agent_returns_zeroes(self, app, pg_conn):
        import uuid as _uuid

        self._seed_run(pg_conn, "u-sched", "success")
        response = self._post(
            app, pg_conn, "u-sched", {"api_key_id": str(_uuid.uuid4())}
        )
        assert response.status_code == 200
        assert all(
            bucket == {"completed": 0, "failed": 0, "skipped": 0}
            for bucket in response.json["runs"].values()
        )


class TestUnifiedLogsBranches:
    def test_schedule_runs_appear_with_level_mapping(self, app, pg_conn):
        helper = TestGetScheduleAnalytics()
        helper._seed_run(pg_conn, "u-tl", "failed")
        helper._seed_run(pg_conn, "u-tl", "success")

        response = _post_logs(app, pg_conn, "u-tl", {"event_type": "schedule"})
        assert response.status_code == 200
        logs = response.json["logs"]
        assert {log["event_type"] for log in logs} == {"schedule"}
        levels = sorted(log["level"] for log in logs)
        assert levels == ["error", "info"]

    def test_failed_webhook_run_renders_once(self, app, pg_conn):
        # A failed activity writes BOTH an error row (except) and an info
        # row (finally) for the same activity_id — the timeline must show
        # the run once, as the error.
        _seed_stack_log(
            pg_conn, user_id="u-wh", endpoint="webhook",
            level="error", activity_id="act-1",
        )
        _seed_stack_log(
            pg_conn, user_id="u-wh", endpoint="webhook",
            level="info", activity_id="act-1",
        )

        response = _post_logs(app, pg_conn, "u-wh", {"event_type": "webhook"})
        assert response.status_code == 200
        logs = response.json["logs"]
        assert len(logs) == 1
        assert logs[0]["level"] == "error"

    def test_successful_webhook_run_still_shows(self, app, pg_conn):
        _seed_stack_log(
            pg_conn, user_id="u-wh2", endpoint="webhook",
            level="info", activity_id="act-ok",
        )
        response = _post_logs(app, pg_conn, "u-wh2", {"event_type": "webhook"})
        assert response.status_code == 200
        assert len(response.json["logs"]) == 1
        assert response.json["logs"][0]["level"] == "info"

    def test_level_filter_applies_per_branch(self, app, pg_conn):
        from application.storage.db.repositories.user_logs import (
            UserLogsRepository,
        )

        UserLogsRepository(pg_conn).insert(
            user_id="u-lvl",
            endpoint="stream_answer",
            data={"action": "stream_answer", "level": "info", "question": "q"},
        )
        _seed_stack_log(pg_conn, user_id="u-lvl", level="error")

        response = _post_logs(app, pg_conn, "u-lvl", {"level": "error"})
        assert response.status_code == 200
        assert [log["level"] for log in response.json["logs"]] == ["error"]

    def test_system_stacks_redacted_on_read(self, app, pg_conn):
        # A row written before write-time redaction existed still holds
        # the reflected provider secret in ``stacks``. The endpoint must
        # scrub it on the way out, not hand it back to the client.
        import json

        from sqlalchemy import text

        pg_conn.execute(
            text(
                """
                INSERT INTO stack_logs
                    (activity_id, endpoint, level, user_id, stacks)
                VALUES
                    ('act-leak', 'stream', 'error', 'u-redact',
                     CAST(:stacks AS jsonb))
                """
            ),
            {
                "stacks": json.dumps(
                    [
                        {
                            "component": "llm",
                            "data": {
                                "api_key": "sk-deployment-secret",
                                "user_api_key": "agent-key",
                                "model": "gpt-x",
                            },
                        }
                    ]
                )
            },
        )

        response = _post_logs(app, pg_conn, "u-redact", {"event_type": "system"})
        assert response.status_code == 200
        logs = response.json["logs"]
        assert len(logs) == 1
        data = logs[0]["stacks"][0]["data"]
        assert data["api_key"] == "[REDACTED]"
        assert data["user_api_key"] == "[REDACTED]"
        assert data["model"] == "gpt-x"

    def test_non_numeric_page_returns_400(self, app, pg_conn):
        response = _post_logs(app, pg_conn, "u", {"page": "abc"})
        assert response.status_code == 400


class TestTokenAnalyticsParamCoercion:
    def test_string_false_disables_side_channel(self, app, pg_conn):
        from application.api.user.analytics.routes import GetTokenAnalytics
        from application.storage.db.repositories.token_usage import (
            TokenUsageRepository,
        )

        TokenUsageRepository(pg_conn).insert(
            user_id="u-coerce", prompt_tokens=100, generated_tokens=0,
            source="title",
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="u-coerce", prompt_tokens=7, generated_tokens=0,
        )

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_token_analytics",
            method="POST",
            json={"include_side_channel": "false"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-coerce"}
            response = GetTokenAnalytics().post()
        assert response.status_code == 200
        # The JSON string "false" must not truthy-coerce to True: the
        # 100 side-channel (title) tokens stay excluded.
        assert sum(response.json["token_usage"].values()) == 7

def _post_resource(app, pg_conn, resource_cls, path, user, body):
    with _patch_analytics_db(pg_conn), app.test_request_context(
        path, method="POST", json=body
    ):
        from flask import request
        request.decoded_token = {"sub": user}
        return resource_cls().post()


class TestUnknownAgentShortCircuits:
    """Messages / feedback mirror the token / tool / schedule contract:
    a filter that doesn't resolve to one of the caller's agents returns
    an explicit empty result, never "all my data" (and never a sentinel
    filter — see TestCrossTenantIsolation)."""

    def test_message_analytics_returns_zeroes(self, app, pg_conn):
        import uuid as _uuid

        from application.api.user.analytics.routes import GetMessageAnalytics

        _seed_conversation_with_messages(pg_conn, "u-msg", count=2)
        response = _post_resource(
            app, pg_conn, GetMessageAnalytics, "/api/get_message_analytics",
            "u-msg", {"api_key_id": str(_uuid.uuid4())},
        )
        assert response.status_code == 200
        assert sum(response.json["messages"].values()) == 0

    def test_feedback_analytics_returns_zeroes(self, app, pg_conn):
        import uuid as _uuid

        from application.api.user.analytics.routes import GetFeedbackAnalytics

        _seed_conversation_with_messages(
            pg_conn, "u-fb0", count=2, feedback_text="like"
        )
        response = _post_resource(
            app, pg_conn, GetFeedbackAnalytics, "/api/get_feedback_analytics",
            "u-fb0", {"api_key_id": str(_uuid.uuid4())},
        )
        assert response.status_code == 200
        assert all(
            bucket == {"positive": 0, "negative": 0}
            for bucket in response.json["feedback"].values()
        )


class TestMessageAnalyticsBuckets:
    @pytest.mark.parametrize("option", ["last_hour", "last_24_hour"])
    def test_minute_and_hour_buckets(self, app, pg_conn, option):
        from application.api.user.analytics.routes import GetMessageAnalytics

        _seed_conversation_with_messages(pg_conn, "u-bkt", count=2)
        response = _post_resource(
            app, pg_conn, GetMessageAnalytics, "/api/get_message_analytics",
            "u-bkt", {"filter_option": option},
        )
        assert response.status_code == 200
        assert sum(response.json["messages"].values()) == 2


class TestFeedbackAnalyticsAgentFilter:
    def test_filters_by_agent_key_or_id(self, app, pg_conn):
        from application.api.user.analytics.routes import GetFeedbackAnalytics
        from application.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create(
            "u-fb", "fb-agent", "published", key="fb-key",
        )
        # count=2 → message 0 'like', message 1 'dislike' per conversation.
        _seed_conversation_with_messages(
            pg_conn, "u-fb", count=2, api_key="fb-key", feedback_text="like"
        )
        _seed_conversation_with_messages(
            pg_conn, "u-fb", count=2, feedback_text="like"
        )

        response = _post_resource(
            app, pg_conn, GetFeedbackAnalytics, "/api/get_feedback_analytics",
            "u-fb", {"api_key_id": str(agent["id"])},
        )
        assert response.status_code == 200
        totals = {"positive": 0, "negative": 0}
        for bucket in response.json["feedback"].values():
            totals["positive"] += bucket["positive"]
            totals["negative"] += bucket["negative"]
        # Only the agent conversation's feedback — not the keyless one.
        assert totals == {"positive": 1, "negative": 1}


class TestTokenAnalyticsGrouping:
    def test_group_by_model_returns_series(self, app, pg_conn):
        from application.api.user.analytics.routes import GetTokenAnalytics
        from application.storage.db.repositories.token_usage import (
            TokenUsageRepository,
        )

        TokenUsageRepository(pg_conn).insert(
            user_id="u-grp", prompt_tokens=10, generated_tokens=5,
            model_id="gpt-x",
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="u-grp", prompt_tokens=1, generated_tokens=2,
        )

        response = _post_resource(
            app, pg_conn, GetTokenAnalytics, "/api/get_token_analytics",
            "u-grp", {"group_by": "model"},
        )
        assert response.status_code == 200
        assert sum(response.json["token_usage"].values()) == 18
        series = response.json["series"]
        # Rows without a model_id group under the 'unknown' key.
        assert set(series) == {"gpt-x", "unknown"}
        assert sum(series["gpt-x"].values()) == 15
        assert sum(series["unknown"].values()) == 3

    def test_filters_by_owned_agent_key_or_id(self, app, pg_conn):
        from application.api.user.analytics.routes import GetTokenAnalytics
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.token_usage import (
            TokenUsageRepository,
        )

        agent = AgentsRepository(pg_conn).create(
            "u-tok", "tok-agent", "published", key="tok-key",
        )
        # External chat traffic stamps the key; headless runs stamp the
        # agent_id — the filter must match either shape.
        TokenUsageRepository(pg_conn).insert(
            user_id="u-tok", api_key="tok-key", prompt_tokens=4,
            generated_tokens=0,
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="u-tok", agent_id=str(agent["id"]), prompt_tokens=2,
            generated_tokens=0,
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="u-tok", prompt_tokens=100, generated_tokens=0,
        )

        response = _post_resource(
            app, pg_conn, GetTokenAnalytics, "/api/get_token_analytics",
            "u-tok", {"api_key_id": str(agent["id"])},
        )
        assert response.status_code == 200
        assert sum(response.json["token_usage"].values()) == 6


class TestScheduleAnalyticsAgentFilter:
    def test_filters_by_owned_agent(self, app, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        helper = TestGetScheduleAnalytics()
        agent = AgentsRepository(pg_conn).create(
            "u-sched2", "sched-agent", "published", key="sk",
        )
        helper._seed_run(pg_conn, "u-sched2", "success", agent_id=str(agent["id"]))
        helper._seed_run(pg_conn, "u-sched2", "failed")  # no agent

        response = helper._post(
            app, pg_conn, "u-sched2", {"api_key_id": str(agent["id"])}
        )
        assert response.status_code == 200
        totals = {"completed": 0, "failed": 0, "skipped": 0}
        for bucket in response.json["runs"].values():
            for key in totals:
                totals[key] += bucket[key]
        assert totals == {"completed": 1, "failed": 0, "skipped": 0}


class TestUnifiedLogsFilters:
    def test_search_matches_summary(self, app, pg_conn):
        from application.storage.db.repositories.user_logs import (
            UserLogsRepository,
        )

        repo = UserLogsRepository(pg_conn)
        repo.insert(
            user_id="u-srch", endpoint="stream",
            data={"question": "how do whales sleep"},
        )
        repo.insert(
            user_id="u-srch", endpoint="stream",
            data={"question": "unrelated"},
        )

        response = _post_logs(app, pg_conn, "u-srch", {"search": "whales"})
        assert response.status_code == 200
        logs = response.json["logs"]
        assert len(logs) == 1
        assert "whales" in logs[0]["question"]

    def test_search_escapes_like_wildcards(self, app, pg_conn):
        from application.storage.db.repositories.user_logs import (
            UserLogsRepository,
        )

        UserLogsRepository(pg_conn).insert(
            user_id="u-srch2", endpoint="stream",
            data={"question": "plain text"},
        )
        # '%' must be matched literally, not as a wildcard.
        response = _post_logs(app, pg_conn, "u-srch2", {"search": "%"})
        assert response.status_code == 200
        assert response.json["logs"] == []

    def test_invalid_event_type_returns_400(self, app, pg_conn):
        response = _post_logs(app, pg_conn, "u", {"event_type": "bogus"})
        assert response.status_code == 400


class TestNewEndpointGuards:
    """401 / invalid-filter guards on the two endpoints new in this PR,
    mirroring the existing per-endpoint guard tests above."""

    @pytest.mark.parametrize(
        "resource_name, path",
        [
            ("GetToolAnalytics", "/api/get_tool_analytics"),
            ("GetScheduleAnalytics", "/api/get_schedule_analytics"),
        ],
    )
    def test_returns_401_unauthenticated(self, app, resource_name, path):
        import application.api.user.analytics.routes as routes

        resource_cls = getattr(routes, resource_name)
        with app.test_request_context(path, method="POST", json={}):
            from flask import request
            request.decoded_token = None
            response = resource_cls().post()
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "resource_name, path",
        [
            ("GetToolAnalytics", "/api/get_tool_analytics"),
            ("GetScheduleAnalytics", "/api/get_schedule_analytics"),
        ],
    )
    def test_invalid_filter_returns_400(self, app, resource_name, path):
        import application.api.user.analytics.routes as routes

        resource_cls = getattr(routes, resource_name)
        with app.test_request_context(
            path, method="POST", json={"filter_option": "nope"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = resource_cls().post()
        assert response.status_code == 400


class TestTokenAnalyticsGroupByAgent:
    def test_group_by_agent_resolves_names(self, app, pg_conn):
        from application.api.user.analytics.routes import GetTokenAnalytics
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.token_usage import (
            TokenUsageRepository,
        )

        agent = AgentsRepository(pg_conn).create(
            "u-grpa", "Billing Bot", "published", key="ga-key",
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="u-grpa", agent_id=str(agent["id"]), prompt_tokens=3,
            generated_tokens=0,
        )
        TokenUsageRepository(pg_conn).insert(
            user_id="u-grpa", prompt_tokens=1, generated_tokens=0,
        )

        response = _post_resource(
            app, pg_conn, GetTokenAnalytics, "/api/get_token_analytics",
            "u-grpa", {"group_by": "agent"},
        )
        assert response.status_code == 200
        # The series is keyed by the agent's display name, not its UUID.
        assert set(response.json["series"]) == {"Billing Bot", "No agent"}


class TestNewEndpointDbErrors:
    @pytest.mark.parametrize(
        "resource_name, path",
        [
            ("GetToolAnalytics", "/api/get_tool_analytics"),
            ("GetScheduleAnalytics", "/api/get_schedule_analytics"),
        ],
    )
    def test_db_error_returns_400(self, app, resource_name, path):
        import application.api.user.analytics.routes as routes

        resource_cls = getattr(routes, resource_name)

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(path, method="POST", json={}):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = resource_cls().post()
        assert response.status_code == 400


class TestUnifiedLogsWorkflowBranch:
    def test_workflow_runs_appear_with_payload(self, app, pg_conn):
        import datetime as _dt

        from application.storage.db.repositories.workflow_runs import (
            WorkflowRunsRepository,
        )
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )

        now = _dt.datetime.now(_dt.timezone.utc)
        wf = WorkflowsRepository(pg_conn).create("u-wf", "My Flow")
        WorkflowRunsRepository(pg_conn).create(
            str(wf["id"]), "u-wf", "failed",
            inputs={"query": "run it"}, started_at=now, ended_at=now,
        )
        WorkflowRunsRepository(pg_conn).create(
            str(wf["id"]), "u-wf", "completed",
            started_at=now, ended_at=now,
        )

        response = _post_logs(app, pg_conn, "u-wf", {"event_type": "workflow"})
        assert response.status_code == 200
        logs = response.json["logs"]
        assert len(logs) == 2
        assert {log["action"] for log in logs} == {"workflow_run"}
        assert sorted(log["level"] for log in logs) == ["error", "info"]
        by_level = {log["level"]: log for log in logs}
        assert by_level["error"]["status"] == "failed"
        assert by_level["error"]["workflow_name"] == "My Flow"
        # Summary falls back to the workflow name when inputs lack a query.
        assert by_level["info"]["question"] == "My Flow"


class TestSharedAgentVisibility:
    """Per-agent dashboards show the agent's full traffic, including
    conversations a *shared* agent's callers create under their own
    user_id. Messages / feedback / schedule must agree with the chat
    timeline, which already exposes that traffic — they used to keep a
    ``c.user_id``/``r.user_id`` clause that hid it (one screen, two
    populations)."""

    def _owned_agent(self, pg_conn, owner):
        from application.storage.db.repositories.agents import AgentsRepository

        return AgentsRepository(pg_conn).create(
            owner, "shared-agent", "published", key="shared-key",
        )

    def test_message_analytics_includes_shared_caller(self, app, pg_conn):
        from application.api.user.analytics.routes import GetMessageAnalytics

        agent = self._owned_agent(pg_conn, "owner-a")
        # Caller B chats with A's shared agent: conversation.user_id = B,
        # agent_id = A's agent.
        _seed_conversation_with_messages(
            pg_conn, "caller-b", count=3, agent_id=str(agent["id"])
        )
        response = _post_resource(
            app, pg_conn, GetMessageAnalytics, "/api/get_message_analytics",
            "owner-a", {"api_key_id": str(agent["id"])},
        )
        assert response.status_code == 200
        assert sum(response.json["messages"].values()) == 3

    def test_feedback_analytics_includes_shared_caller(self, app, pg_conn):
        from application.api.user.analytics.routes import GetFeedbackAnalytics

        agent = self._owned_agent(pg_conn, "owner-a")
        _seed_conversation_with_messages(
            pg_conn, "caller-b", count=2, agent_id=str(agent["id"]),
            feedback_text="like",
        )
        response = _post_resource(
            app, pg_conn, GetFeedbackAnalytics, "/api/get_feedback_analytics",
            "owner-a", {"api_key_id": str(agent["id"])},
        )
        assert response.status_code == 200
        totals = {"positive": 0, "negative": 0}
        for bucket in response.json["feedback"].values():
            totals["positive"] += bucket["positive"]
            totals["negative"] += bucket["negative"]
        assert totals == {"positive": 1, "negative": 1}

    def test_schedule_analytics_includes_shared_caller(self, app, pg_conn):
        helper = TestGetScheduleAnalytics()
        agent = self._owned_agent(pg_conn, "owner-a")
        # Run created by caller B against A's agent (scheduler tool stamps
        # the caller's user_id).
        helper._seed_run(
            pg_conn, "caller-b", "success", agent_id=str(agent["id"])
        )
        response = helper._post(
            app, pg_conn, "owner-a", {"api_key_id": str(agent["id"])}
        )
        assert response.status_code == 200
        completed = sum(b["completed"] for b in response.json["runs"].values())
        assert completed == 1

    def test_schedule_timeline_includes_shared_caller(self, app, pg_conn):
        helper = TestGetScheduleAnalytics()
        agent = self._owned_agent(pg_conn, "owner-a")
        helper._seed_run(
            pg_conn, "caller-b", "failed", agent_id=str(agent["id"])
        )
        response = _post_logs(
            app, pg_conn, "owner-a",
            {"api_key_id": str(agent["id"]), "event_type": "schedule"},
        )
        assert response.status_code == 200
        assert len(response.json["logs"]) == 1
        assert response.json["logs"][0]["level"] == "error"
