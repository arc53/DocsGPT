"""Tests for docsgpt/api/user/analytics/routes.py.

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
        "docsgpt.api.user.analytics.routes.db_readonly", _yield_conn
    ):
        yield


def _seed_conversation_with_messages(
    pg_conn, user_id, *, count=3, api_key=None, feedback_text=None,
    agent_id=None,
):
    from docsgpt.storage.db.repositories.conversations import (
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
        from docsgpt.api.user.analytics.routes import _range_for_filter

        assert _range_for_filter("bogus") is None

    @pytest.mark.parametrize(
        "option",
        ["last_hour", "last_24_hour", "last_7_days", "last_15_days", "last_30_days"],
    )
    def test_returns_start_end_for_supported(self, option):
        from docsgpt.api.user.analytics.routes import _range_for_filter

        got = _range_for_filter(option)
        assert got is not None
        start, end, bucket_unit, pg_fmt = got
        assert start < end
        assert bucket_unit in {"minute", "hour", "day"}


class TestResolveAgent:
    def test_no_agent_when_no_id(self, pg_conn):
        from docsgpt.api.user.analytics.routes import _resolve_agent

        assert _resolve_agent(pg_conn, None, "u") == (None, None, None)
        assert _resolve_agent(pg_conn, "", "u") == (None, None, None)

    def test_returns_key_and_id_for_owned_agent(self, pg_conn):
        from docsgpt.api.user.analytics.routes import _resolve_agent
        from docsgpt.storage.db.repositories.agents import AgentsRepository

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
        from docsgpt.api.user.analytics.routes import _resolve_agent
        from docsgpt.storage.db.repositories.agents import AgentsRepository

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
        from docsgpt.api.user.analytics.routes import _resolve_agent
        from docsgpt.storage.db.repositories.agents import AgentsRepository

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
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

        with app.test_request_context(
            "/api/get_message_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetMessageAnalytics().post()
        assert response.status_code == 401

    def test_invalid_filter_returns_400(self, app):
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

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
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

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
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics
        from docsgpt.storage.db.repositories.agents import AgentsRepository

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
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/get_message_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetMessageAnalytics().post()
        assert response.status_code == 400


class TestGetTokenAnalytics:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics

        with app.test_request_context(
            "/api/get_token_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetTokenAnalytics().post()
        assert response.status_code == 401

    def test_invalid_filter_returns_400(self, app):
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics

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
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics

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
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/get_token_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetTokenAnalytics().post()
        assert response.status_code == 400


class TestGetFeedbackAnalytics:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.analytics.routes import GetFeedbackAnalytics

        with app.test_request_context(
            "/api/get_feedback_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetFeedbackAnalytics().post()
        assert response.status_code == 401

    def test_invalid_filter_returns_400(self, app):
        from docsgpt.api.user.analytics.routes import GetFeedbackAnalytics

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
        from docsgpt.api.user.analytics.routes import GetFeedbackAnalytics

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
        from docsgpt.api.user.analytics.routes import GetFeedbackAnalytics

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(
            "/api/get_feedback_analytics", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetFeedbackAnalytics().post()
        assert response.status_code == 400


class TestGetUserLogs:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.analytics.routes import GetUserLogs

        with app.test_request_context(
            "/api/get_user_logs", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = GetUserLogs().post()
        assert response.status_code == 401

    def test_returns_logs_list_paginated(self, app, pg_conn):
        from docsgpt.api.user.analytics.routes import GetUserLogs
        from docsgpt.storage.db.repositories.user_logs import (
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
        from docsgpt.api.user.analytics.routes import GetUserLogs
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.user_logs import (
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

    def test_webhook_logs_match_by_agent_id_after_key_rotation(
        self, app, pg_conn,
    ):
        """A webhook activity-log row stamped with the agent's id but an
        *old* api_key (the state after a key rotation) must still surface on
        the agent's timeline via the stable agent_id join."""
        from docsgpt.api.user.analytics.routes import GetUserLogs
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.stack_logs import (
            StackLogsRepository,
        )

        user = "u-logs-rotate"
        agent = AgentsRepository(pg_conn).create(
            user, "a", "published", key="current-key",
        )
        stack_repo = StackLogsRepository(pg_conn)
        # Written under the previous key, but carries the stable agent_id.
        stack_repo.insert(
            activity_id="wh-rotated",
            endpoint="webhook",
            level="info",
            user_id="external-caller",
            api_key="rotated-away-key",
            agent_id=str(agent["id"]),
        )
        # A different agent's webhook log must NOT leak in.
        stack_repo.insert(
            activity_id="wh-other",
            endpoint="webhook",
            level="info",
            user_id="external-caller",
            api_key="unrelated-key",
            agent_id="99999999-9999-9999-9999-999999999999",
        )

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_user_logs",
            method="POST",
            json={"api_key_id": str(agent["id"]), "event_type": "webhook"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetUserLogs().post()
        assert response.status_code == 200
        logs = response.json["logs"]
        assert len(logs) == 1
        assert logs[0]["id"]  # the rotated-away row surfaced via agent_id

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.analytics.routes import GetUserLogs

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.analytics.routes.db_readonly", _broken
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

    from docsgpt.storage.db.repositories.stack_logs import (
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
    from docsgpt.api.user.analytics.routes import GetUserLogs

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
        from docsgpt.storage.db.repositories.agents import AgentsRepository

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
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.token_usage import (
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
        from docsgpt.api.user.analytics.routes import GetToolAnalytics

        with _patch_analytics_db(pg_conn), app.test_request_context(
            "/api/get_tool_analytics", method="POST", json=body
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return GetToolAnalytics().post()

    def test_counts_terminal_attempts_only(self, app, pg_conn):
        from docsgpt.storage.db.repositories.tool_call_attempts import (
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
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.tool_call_attempts import (
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

        from docsgpt.storage.db.repositories.schedule_runs import (
            ScheduleRunsRepository,
        )
        from docsgpt.storage.db.repositories.schedules import (
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
        from docsgpt.api.user.analytics.routes import GetScheduleAnalytics

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
        from docsgpt.storage.db.repositories.user_logs import (
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
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics
        from docsgpt.storage.db.repositories.token_usage import (
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

        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

        _seed_conversation_with_messages(pg_conn, "u-msg", count=2)
        response = _post_resource(
            app, pg_conn, GetMessageAnalytics, "/api/get_message_analytics",
            "u-msg", {"api_key_id": str(_uuid.uuid4())},
        )
        assert response.status_code == 200
        assert sum(response.json["messages"].values()) == 0

    def test_feedback_analytics_returns_zeroes(self, app, pg_conn):
        import uuid as _uuid

        from docsgpt.api.user.analytics.routes import GetFeedbackAnalytics

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
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

        _seed_conversation_with_messages(pg_conn, "u-bkt", count=2)
        response = _post_resource(
            app, pg_conn, GetMessageAnalytics, "/api/get_message_analytics",
            "u-bkt", {"filter_option": option},
        )
        assert response.status_code == 200
        assert sum(response.json["messages"].values()) == 2


class TestFeedbackAnalyticsAgentFilter:
    def test_filters_by_agent_key_or_id(self, app, pg_conn):
        from docsgpt.api.user.analytics.routes import GetFeedbackAnalytics
        from docsgpt.storage.db.repositories.agents import AgentsRepository

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
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics
        from docsgpt.storage.db.repositories.token_usage import (
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
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.token_usage import (
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
        from docsgpt.storage.db.repositories.agents import AgentsRepository

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
        from docsgpt.storage.db.repositories.user_logs import (
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
        from docsgpt.storage.db.repositories.user_logs import (
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
        import docsgpt.api.user.analytics.routes as routes

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
        import docsgpt.api.user.analytics.routes as routes

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
        from docsgpt.api.user.analytics.routes import GetTokenAnalytics
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.token_usage import (
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
        import docsgpt.api.user.analytics.routes as routes

        resource_cls = getattr(routes, resource_name)

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.analytics.routes.db_readonly", _broken
        ), app.test_request_context(path, method="POST", json={}):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = resource_cls().post()
        assert response.status_code == 400


class TestUnifiedLogsWorkflowBranch:
    def test_workflow_runs_appear_with_payload(self, app, pg_conn):
        import datetime as _dt

        from docsgpt.storage.db.repositories.workflow_runs import (
            WorkflowRunsRepository,
        )
        from docsgpt.storage.db.repositories.workflows import (
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
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        return AgentsRepository(pg_conn).create(
            owner, "shared-agent", "published", key="shared-key",
        )

    def test_message_analytics_includes_shared_caller(self, app, pg_conn):
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

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
        from docsgpt.api.user.analytics.routes import GetFeedbackAnalytics

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


# ---- conversation insights, docs gaps and Logs labels (issue 004) -------------------------------------------


_TAG = "a1b2c3d4"
_TURN = {"fully answered": 0.5, "partially answered": 0.1, "declined, no information": 0.2,
         "asked a clarifying question": 0.0, "not a request": 0.2}
_GAP = {"docs missing": 0.24, "other": 0.06, "none": 0.7}


@pytest.fixture
def analytics_on(monkeypatch):
    """The operator switch on and the model available, without loading one."""
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
    monkeypatch.setattr("docsgpt.decisions.available", lambda: True)


def _model_version():
    from docsgpt.decisions.models import V02, version

    return version(V02)


def _insert_message(conn, cid, position, prompt, response="Here is how.", *, ago_minutes=120, sources=None):
    import json

    from sqlalchemy import text

    return conn.execute(
        text(
            """
            INSERT INTO conversation_messages
                (conversation_id, position, prompt, response, status, sources, timestamp, updated_at)
            VALUES (CAST(:cid AS uuid), :position, :prompt, :response, 'complete', CAST(:sources AS jsonb),
                    now() - make_interval(mins => :ago), now() - make_interval(mins => :ago))
            RETURNING CAST(id AS text)
            """
        ),
        {"cid": cid, "position": position, "prompt": prompt, "response": response, "ago": ago_minutes,
         "sources": json.dumps(sources if sources is not None else
                               [{"title": "Install", "source": "docs/install.md", "source_id": None,
                                 "text": "pip install docsgpt"}])},
    ).scalar()


def _analytics_agent(conn, owner="owner", **analytics):
    from docsgpt.storage.db.repositories.agents import AgentsRepository

    analytics.setdefault("topics", [{"id": _TAG, "name": "Pricing question", "description": "Asks about price.",
                                     "overlap": True}])
    return AgentsRepository(conn).create(
        owner, "Docs bot", "published", key=f"key-{owner}", config={"analytics": analytics},
    )


def _labelled_conversation(conn, user, *, agent_id=None, ago_minutes=120, schema_hash=None, lang="en",
                           sources=None, frustrated=0.8, gap=None, topics=None, turn=None):
    """Two turns and their labels, as the sweep writes them: turn rows on each answer, the reaction to the first
    answer on it (pointing at the reply), the request type and effective topic of each message, goal met and a
    tag on the conversation."""
    from docsgpt.analytics import schema
    from docsgpt.storage.db.repositories.conversation_labels import ConversationLabelsRepository
    from docsgpt.storage.db.repositories.conversations import ConversationsRepository

    cid = str(ConversationsRepository(conn).create(user, "c", agent_id=agent_id)["id"])
    first = _insert_message(conn, cid, 0, "How do I install it?", ago_minutes=ago_minutes, sources=sources)
    second = _insert_message(conn, cid, 1, "that did not work at all!", ago_minutes=ago_minutes - 1,
                             sources=sources)
    base = {"conversation_id": cid, "user_id": user, "agent_id": agent_id, "lang": lang,
            "schema_hash": schema_hash or schema.SCHEMA_HASH, "model_version": _model_version()}

    def at(minutes):
        return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)

    rows = []
    for message, minutes in ((first, ago_minutes), (second, ago_minutes - 1)):
        rows += [
            {**base, "message_id": message, "level": "turn", "label": "answer_status",
             "probabilities": turn or _TURN, "occurred_at": at(minutes)},
            {**base, "message_id": message, "level": "turn", "label": "gap_type", "derived": True,
             "probabilities": gap or _GAP, "occurred_at": at(minutes)},
            {**base, "message_id": message, "level": "message", "label": "request_type",
             "probabilities": {"how-to": 0.7, "troubleshooting": 0.3}, "occurred_at": at(minutes)},
        ]
        if topics is not None:
            rows.append({**base, "message_id": message, "level": "message", "label": "topic_effective",
                         "derived": True, "top": max(topics, key=topics.get), "probabilities": topics,
                         "occurred_at": at(minutes)})
    reply = {**base, "message_id": first, "reply_message_id": second, "level": "reaction",
             "occurred_at": at(ago_minutes - 1)}
    rows += [
        {**reply, "label": "reaction", "probabilities": {"correction or pushback": 0.6, "follow-up": 0.4}},
        {**reply, "label": "frustrated", "probabilities": {"yes": frustrated, "no": 1 - frustrated}},
        {**reply, "label": "asks_human", "probabilities": {"yes": 0.1, "no": 0.9}},
        {**reply, "label": "sentiment", "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1}},
        {**base, "level": "conversation", "label": "goal_met", "probabilities": {"yes": 0.3, "no": 0.7},
         "occurred_at": at(ago_minutes - 1)},
        {**base, "level": "conversation", "label": f"tag:{_TAG}", "probabilities": {"yes": 0.9, "no": 0.1},
         "occurred_at": at(ago_minutes - 1)},
    ]
    ConversationLabelsRepository(conn).upsert_many(rows)
    return cid, first, second


def _insights(app, pg_conn, user, body):
    from docsgpt.api.user.analytics.routes import GetConversationInsights

    return _post_resource(app, pg_conn, GetConversationInsights, "/api/get_conversation_insights", user, body)


def _gaps(app, pg_conn, user, body):
    from docsgpt.api.user.analytics.routes import GetDocsGaps

    return _post_resource(app, pg_conn, GetDocsGaps, "/api/get_docs_gaps", user, body)


class TestConversationInsights:
    def test_totals_series_coverage_and_shape(self, app, pg_conn, analytics_on, monkeypatch):
        from docsgpt.analytics import calibration, derive, insights

        # Days stay days however few answers fill them; merging them into weeks has its own test.
        monkeypatch.setattr(insights, "MIN_SAMPLE", 0)
        agent = _analytics_agent(pg_conn)
        agent_id = str(agent["id"])
        _labelled_conversation(pg_conn, "owner", agent_id=agent_id)
        _labelled_conversation(pg_conn, "owner", agent_id=agent_id, ago_minutes=60 * 30)

        response = _insights(app, pg_conn, "owner", {"api_key_id": agent_id, "filter_option": "last_7_days"})
        assert response.status_code == 200
        data = response.json
        assert data["success"] and data["enabled"] and data["available"]
        assert data["overlapping"] == [{"id": _TAG, "name": "Pricing question"}]
        assert data["one_pick"] == []
        assert data["coverage"] == {"turns": 4, "labelled_turns": 4, "replies": 2, "labelled_replies": 2,
                                    "conversations": 2, "labelled_conversations": 2,
                                    "unlabelled_recent_turns": 0, "unlabelled_older_turns": 0,
                                    "failed_turns": 0}
        assert data["languages"] == {"en": 4}
        assert data["language_warnings"] == []

        totals = data["totals"]
        assert set(totals) == {"answer_status", "gap_type", "reaction", "request_type", "sentiment", "frustrated",
                               "asks_human", "goal_met", f"tag:{_TAG}"}
        assert {label: entry["tier"] for label, entry in totals.items()} == {
            "answer_status": "dashboard", "gap_type": "estimated", "reaction": "estimated",
            "request_type": "estimated", "sentiment": "dashboard", "frustrated": "dashboard",
            "asks_human": "dashboard", "goal_met": "dashboard", f"tag:{_TAG}": "dashboard",
        }
        assert set(totals["sentiment"]["options"]) == {"negative", "neutral", "positive"}
        assert set(totals["goal_met"]["options"]) == {"yes"}
        assert set(totals[f"tag:{_TAG}"]["options"]) == {"yes"}

        # The interval is derive.rate's, widened by the label's calibration error.
        frustrated = totals["frustrated"]
        assert frustrated["n"] == 2
        rate, low, high = derive.rate([0.8, 0.8], calibration.ece("frustrated", _model_version()))
        assert frustrated["options"]["yes"] == {
            "expected": 1.6, "rate": pytest.approx(rate, abs=1e-4), "low": pytest.approx(low, abs=1e-4),
            "high": pytest.approx(high, abs=1e-4),
        }
        gap = totals["gap_type"]["options"]["docs missing"]
        rate, low, high = derive.rate([0.24] * 4, calibration.ece("gap_type", _model_version()))
        assert gap["expected"] == pytest.approx(0.96)
        assert (gap["rate"], gap["low"], gap["high"]) == (
            pytest.approx(rate, abs=1e-4), pytest.approx(low, abs=1e-4), pytest.approx(high, abs=1e-4))
        assert totals["gap_type"]["n"] == 4

        # Two buckets with one conversation each; the series sum to the totals.
        series = {entry["bucket"]: entry["labels"] for entry in data["series"]}
        assert data["bucket_unit"] == "day"
        assert len(data["series"]) == 7
        filled = [labels for labels in series.values() if labels["answer_status"]["n"]]
        assert len(filled) == 2
        assert all(labels["answer_status"]["n"] == 2 for labels in filled)
        assert set(filled[0]) == {"answer_status", "reaction", "request_type", "sentiment", "frustrated",
                                  "asks_human", "goal_met"}
        assert sum(labels["frustrated"]["options"]["yes"] for labels in series.values()) == pytest.approx(1.6)
        assert sum(labels["sentiment"]["options"]["negative"] for labels in series.values()) == pytest.approx(1.4)
        empty = next(labels for labels in series.values() if not labels["answer_status"]["n"])
        assert empty["answer_status"]["options"]["fully answered"] == 0

    def test_sparse_days_merge_into_weeks(self, app, pg_conn, analytics_on):
        """Four answers in 30 days: a day holds too few to read as a mix, so the series is weekly."""
        from docsgpt.analytics import insights

        _labelled_conversation(pg_conn, "u-weeks")
        _labelled_conversation(pg_conn, "u-weeks", ago_minutes=60 * 24 * 12)
        data = _insights(app, pg_conn, "u-weeks", {"filter_option": "last_30_days"}).json
        assert data["bucket_unit"] == "week"
        today = datetime.datetime.now(datetime.timezone.utc).date()
        days = [today - datetime.timedelta(days=ago) for ago in range(29, -1, -1)]
        mondays = list(dict.fromkeys(insights.coarse_key(day.isoformat(), "week") for day in days))
        assert len(data["series"]) == len(mondays)
        # Each week is named by its first day in the window and ends on its last.
        assert data["series"][0]["bucket"] == days[0].isoformat()
        assert data["series"][-1]["bucket_end"] == days[-1].isoformat()
        assert all(entry["bucket"] <= entry["bucket_end"] for entry in data["series"])
        assert sum(entry["labels"]["answer_status"]["n"] for entry in data["series"]) == 4
        assert sum(entry["labels"]["sentiment"]["options"]["negative"] for entry in data["series"]) == (
            pytest.approx(1.4))

    def test_previous_period_totals(self, app, pg_conn, analytics_on):
        """The headline labels' totals over the period of the same length just before the window."""
        from docsgpt.analytics import insights

        _labelled_conversation(pg_conn, "u-prev")
        _labelled_conversation(pg_conn, "u-prev", ago_minutes=60 * 24 * 9)
        _labelled_conversation(pg_conn, "u-prev", ago_minutes=60 * 24 * 20)
        data = _insights(app, pg_conn, "u-prev", {"filter_option": "last_7_days"}).json
        previous = data["previous"]
        assert set(previous) == set(insights.PREVIOUS_LABELS)
        # The conversation 9 days back only: 20 days back is before the previous period too.
        assert previous["answer_status"]["n_turns"] == 2
        assert previous["reaction"]["n"] == previous["sentiment"]["n"] == 1
        assert previous["sentiment"]["options"]["negative"]["expected"] == pytest.approx(0.7)
        assert data["totals"]["answer_status"]["n_turns"] == 2

    def test_answer_status_rates_are_over_requests(self, app, pg_conn, analytics_on):
        from docsgpt.analytics import calibration

        _labelled_conversation(pg_conn, "u-req")
        _labelled_conversation(pg_conn, "u-req")
        data = _insights(app, pg_conn, "u-req", {"filter_option": "last_24_hour"}).json
        status = data["totals"]["answer_status"]
        # four turns, each 0.2 a greeting: 3.2 requests
        assert status["n_turns"] == 4
        assert status["n_requests"] == pytest.approx(3.2)
        assert status["n"] == 3
        fully = status["options"]["fully answered"]
        assert fully["rate"] == pytest.approx(2.0 / 3.2, abs=1e-4)
        assert (fully["rate"], fully["low"], fully["high"]) == tuple(
            pytest.approx(v, abs=1e-4)
            for v in calibration.interval("answer_status", 2.0, 3.2, _model_version())
        )
        greeting = status["options"]["not a request"]
        assert greeting["rate"] == pytest.approx(0.2, abs=1e-4)
        # gap_type stays over every labelled turn
        assert data["totals"]["gap_type"]["n"] == 4

    def test_owner_sees_shared_agent_traffic(self, app, pg_conn, analytics_on):
        agent = _analytics_agent(pg_conn, owner="owner-a")
        _labelled_conversation(pg_conn, "caller-b", agent_id=str(agent["id"]))
        data = _insights(app, pg_conn, "owner-a", {"api_key_id": str(agent["id"])}).json
        assert data["totals"]["frustrated"]["n"] == 1
        assert data["coverage"]["turns"] == 2
        # The owner's own (global) view holds only their own conversations.
        mine = _insights(app, pg_conn, "owner-a", {}).json
        assert mine["coverage"]["turns"] == 0
        assert mine["totals"]["frustrated"]["n"] == 0
        assert mine["overlapping"] == [] and mine["one_pick"] == []

    def test_unknown_agent_is_empty(self, app, pg_conn, analytics_on):
        import uuid as _uuid

        _labelled_conversation(pg_conn, "u-unknown")
        data = _insights(app, pg_conn, "u-unknown", {"api_key_id": str(_uuid.uuid4())}).json
        assert data["success"] is True
        assert data["enabled"] is False
        assert data["totals"] == {} and data["series"] == [] and data["previous"] == {}
        assert data["coverage"]["turns"] == 0

    def test_other_schema_hash_is_ignored(self, app, pg_conn, analytics_on):
        _labelled_conversation(pg_conn, "u-hash")
        _labelled_conversation(pg_conn, "u-hash", schema_hash="000000000000")
        data = _insights(app, pg_conn, "u-hash", {}).json
        assert data["totals"]["frustrated"]["n"] == 1
        assert data["coverage"]["turns"] == 4
        assert data["coverage"]["labelled_turns"] == 2

    def test_off_switch_and_agent_opt_out(self, app, pg_conn, analytics_on, monkeypatch):
        from docsgpt.core.settings import settings

        agent = _analytics_agent(pg_conn, enabled=False)
        _labelled_conversation(pg_conn, "owner", agent_id=str(agent["id"]))
        data = _insights(app, pg_conn, "owner", {"api_key_id": str(agent["id"])}).json
        assert (data["available"], data["enabled"], data["totals"]) == (True, False, {})
        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        data = _insights(app, pg_conn, "owner", {}).json
        assert (data["available"], data["enabled"]) == (False, False)

    def test_language_mix_and_warnings(self, app, pg_conn, analytics_on):
        _labelled_conversation(pg_conn, "u-lang")
        _labelled_conversation(pg_conn, "u-lang", lang="ru")
        _labelled_conversation(pg_conn, "u-lang", lang="ko")
        data = _insights(app, pg_conn, "u-lang", {}).json
        assert data["languages"] == {"en": 2, "ru": 2, "other": 2}
        assert data["language_warnings"] == ["answer_status", "gap_type", "reaction"]

    def test_topic_effective_appears_with_rows(self, app, pg_conn, analytics_on):
        agent = _analytics_agent(pg_conn, owner="u-topic")
        _labelled_conversation(pg_conn, "u-topic", agent_id=str(agent["id"]),
                               topics={"install": 0.75, "none of these": 0.25})
        data = _insights(app, pg_conn, "u-topic", {"api_key_id": str(agent["id"])}).json
        topic = data["totals"]["topic_effective"]
        assert topic["tier"] == "experimental"
        assert topic["options"]["install"]["expected"] == 1.5
        assert "topic_effective" in data["series"][-1]["labels"]

    def test_one_pick_lists_the_topic_question_the_agent_asks(self, app, pg_conn, analytics_on):
        agent = _analytics_agent(pg_conn, topics=[
            {"id": "billing01", "name": "Billing"}, {"id": "setup0001", "name": "setup"},
            {"id": _TAG, "name": "Pricing question", "overlap": True}])
        data = _insights(app, pg_conn, "owner", {"api_key_id": str(agent["id"])}).json
        assert data["one_pick"] == ["Billing", "setup"]
        assert data["overlapping"] == [{"id": _TAG, "name": "Pricing question"}]

    def test_the_account_view_has_no_topics(self, app, pg_conn, analytics_on):
        """Each agent has its own list, so one chart over all of them would mix unrelated lists."""
        _labelled_conversation(pg_conn, "u-topic", topics={"install": 0.75, "none of these": 0.25})
        data = _insights(app, pg_conn, "u-topic", {}).json
        assert "topic_effective" not in data["totals"]
        assert all("topic_effective" not in bucket["labels"] for bucket in data["series"])

    def test_invalid_filter_is_400(self, app, pg_conn, analytics_on):
        assert _insights(app, pg_conn, "u", {"filter_option": "bogus"}).status_code == 400

    def test_coverage_splits_unlabelled_turns_at_the_labelling_window(self, app, pg_conn, analytics_on,
                                                                       monkeypatch):
        """Unlabelled answers inside the sweep's window are still to come; older ones never are."""
        from docsgpt.core.settings import settings
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository

        monkeypatch.setattr(settings, "ANALYTICS_BACKFILL_DAYS", 7)
        _labelled_conversation(pg_conn, "u-window")
        for days_ago in (2, 10, 20):
            cid = str(ConversationsRepository(pg_conn).create("u-window", "c")["id"])
            _insert_message(pg_conn, cid, 0, "How do I install it?", ago_minutes=days_ago * 24 * 60)
        before = datetime.datetime.now(datetime.timezone.utc)
        data = _insights(app, pg_conn, "u-window", {"filter_option": "last_30_days"}).json
        coverage = data["coverage"]
        assert (coverage["turns"], coverage["labelled_turns"]) == (5, 2)
        assert (coverage["unlabelled_recent_turns"], coverage["unlabelled_older_turns"]) == (1, 2)
        assert data["backfill_days"] == 7
        labelling_from = datetime.datetime.fromisoformat(data["labelling_from"].replace("Z", "+00:00"))
        assert abs((before - datetime.timedelta(days=7) - labelling_from).total_seconds()) < 60

    def test_off_agent_still_says_the_labelling_window(self, app, pg_conn, analytics_on):
        agent = _analytics_agent(pg_conn, enabled=False)
        data = _insights(app, pg_conn, "owner", {"api_key_id": str(agent["id"])}).json
        assert data["enabled"] is False
        assert data["coverage"]["unlabelled_recent_turns"] == data["coverage"]["failed_turns"] == 0
        assert data["backfill_days"] >= 1 and data["labelling_from"]


class TestDocsGaps:
    def test_groups_by_page_with_trend_and_examples(self, app, pg_conn, analytics_on):
        install = [{"title": "Install", "source": "docs/install.md", "text": "x"}]
        auth = [{"title": "Auth", "source": "docs/auth.md", "text": "x"}]
        sure = {"docs missing": 0.9, "none": 0.1}
        cid, first, _second = _labelled_conversation(pg_conn, "u-gap", sources=install, gap=sure)
        # 0.3 a turn: a group, but no turn clears the example threshold
        _labelled_conversation(pg_conn, "u-gap", sources=auth, gap={"docs missing": 0.3})
        _labelled_conversation(pg_conn, "u-gap", sources=[{"title": "Rare", "source": "docs/rare.md"}])  # 0.48
        _labelled_conversation(pg_conn, "u-gap", sources=install, gap=sure, ago_minutes=60 * 24 * 9)
        _labelled_conversation(pg_conn, "u-gap", sources=[], gap=sure)

        response = _gaps(app, pg_conn, "u-gap", {"filter_option": "last_7_days", "group_by": "page"})
        assert response.status_code == 200
        data = response.json
        assert data["enabled"] is True and data["group_by"] == "page"
        rows = {row["key"]: row for row in data["rows"]}
        assert set(rows) == {"docs/install.md", "docs/auth.md", None}
        top = data["rows"][0]
        assert top["key"] in ("docs/install.md", None)
        page = rows["docs/install.md"]
        assert page["name"] == "Install"
        assert page["expected_gaps"] == pytest.approx(1.8)
        assert page["turns"] == 2
        assert page["previous_expected"] == pytest.approx(1.8)
        assert page["rate"] == pytest.approx(0.9, abs=1e-4)
        assert 0 <= page["low"] < page["rate"] < page["high"] <= 1
        assert [example["message_id"] for example in page["examples"]][0] in (first, _second)
        example = page["examples"][0]
        assert example["conversation_id"] == cid
        assert example["p"] == pytest.approx(0.9)
        assert example["prompt"] in ("How do I install it?", "that did not work at all!")
        assert example["timestamp"].endswith("Z")
        assert rows["docs/auth.md"]["examples"] == []
        assert rows[None]["name"] is None
        # no stored source_id: no source name
        assert page["source"] is None
        # the window before holds the 9-day-old conversation's two labelled turns
        assert data["previous_labelled"] == 2

    def test_page_groups_name_their_majority_source(self, app, pg_conn, analytics_on):
        import uuid

        from docsgpt.storage.db.repositories.sources import SourcesRepository

        core = SourcesRepository(pg_conn).create("Core pages", user_id="u-ps")
        other = SourcesRepository(pg_conn).create("Old docs", user_id="u-ps")

        def page(source_id, url="https://docs.example/install"):
            return [{"title": "Install | Example Docs", "source": url, "source_id": source_id, "text": "x"}]

        # one URL indexed by two sources is one row; the source most of its turns came from names it
        _labelled_conversation(pg_conn, "u-ps", sources=page(str(core["id"])), gap={"docs missing": 0.9})
        _labelled_conversation(pg_conn, "u-ps", sources=page(str(core["id"])), gap={"docs missing": 0.9})
        _labelled_conversation(pg_conn, "u-ps", sources=page(str(other["id"])), gap={"docs missing": 0.9})
        # a deleted source has no name back
        _labelled_conversation(pg_conn, "u-ps", sources=page(str(uuid.uuid4()), "https://docs.example/gone"),
                               gap={"docs missing": 0.9})
        data = _gaps(app, pg_conn, "u-ps", {"group_by": "page"}).json
        rows = {row["key"]: row for row in data["rows"]}
        assert rows["https://docs.example/install"]["source"] == "Core pages"
        assert rows["https://docs.example/install"]["name"] == "Install | Example Docs"
        assert rows["https://docs.example/gone"]["source"] is None
        # nothing labelled in the window before
        assert data["previous_labelled"] == 0
        # the other groupings carry no source line
        assert all(row["source"] is None for row in _gaps(app, pg_conn, "u-ps", {"group_by": "source"}).json["rows"])

    def test_gap_groups_select_the_page_source_id(self, pg_conn):
        import uuid

        from docsgpt.analytics import schema
        from docsgpt.storage.db.repositories.conversation_labels import ConversationLabelsRepository, Scope

        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        for source_id in (a, b, a):
            _labelled_conversation(pg_conn, "u-sid", gap={"docs missing": 0.9}, sources=[
                {"title": "Install", "source": "docs/install.md", "source_id": source_id, "text": "x"}])
        now = datetime.datetime.now(datetime.timezone.utc)
        repo = ConversationLabelsRepository(pg_conn)
        args = (Scope(user_id="u-sid"), schema.SCHEMA_HASH, now - datetime.timedelta(days=7), now,
                now - datetime.timedelta(days=14), 10, 0.5)
        assert [(g["key"], g["source_id"]) for g in repo.gap_groups("page", *args)] == [("docs/install.md", a)]
        assert repo.gap_labelled(Scope(user_id="u-sid"), schema.SCHEMA_HASH, now - datetime.timedelta(days=7),
                                 now) == 6

    def test_groups_by_source_name(self, app, pg_conn, analytics_on):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        source = SourcesRepository(pg_conn).create("Product docs", user_id="u-src")
        stored = [{"title": "Install", "source": "docs/install.md", "source_id": str(source["id"]), "text": "x"}]
        _labelled_conversation(pg_conn, "u-src", sources=stored, gap={"docs missing": 0.5})
        rows = _gaps(app, pg_conn, "u-src", {"group_by": "source"}).json["rows"]
        assert [(row["key"], row["name"], row["turns"]) for row in rows] == [
            (str(source["id"]), "Product docs", 2)]

    def test_groups_by_topic_weighted(self, app, pg_conn, analytics_on):
        _labelled_conversation(pg_conn, "u-tg", topics={"install": 0.75, "auth": 0.25},
                               gap={"docs missing": 0.8})
        rows = {row["key"]: row for row in _gaps(app, pg_conn, "u-tg", {"group_by": "topic"}).json["rows"]}
        # under half an expected gap: auth's 2 x 0.8 x 0.25 = 0.4 is left out
        assert set(rows) == {"install"}
        assert rows["install"]["expected_gaps"] == pytest.approx(1.2)
        assert rows["install"]["turns"] == 2  # 1.5 turns, rounded
        assert rows["install"]["rate"] == pytest.approx(0.8, abs=1e-4)
        assert len(rows["install"]["examples"]) == 2
        assert rows["install"]["examples"][0]["p"] == pytest.approx(0.6)

    def test_scoping_and_validation(self, app, pg_conn, analytics_on):
        import uuid as _uuid

        agent = _analytics_agent(pg_conn, owner="owner-a")
        _labelled_conversation(pg_conn, "caller-b", agent_id=str(agent["id"]), gap={"docs missing": 0.9})
        shared = _gaps(app, pg_conn, "owner-a", {"api_key_id": str(agent["id"])}).json
        assert len(shared["rows"]) == 1
        assert _gaps(app, pg_conn, "owner-a", {}).json["rows"] == []
        unknown = _gaps(app, pg_conn, "owner-a", {"api_key_id": str(_uuid.uuid4())}).json
        assert unknown == {"success": True, "enabled": False, "group_by": "page", "previous_labelled": 0,
                           "rows": []}
        _labelled_conversation(pg_conn, "u-other-hash", schema_hash="000000000000", gap={"docs missing": 0.9})
        assert _gaps(app, pg_conn, "u-other-hash", {}).json["rows"] == []
        for body in ({"group_by": "folder"}, {"limit": 51}, {"limit": "x"}, {"filter_option": "bogus"}):
            assert _gaps(app, pg_conn, "owner-a", body).status_code == 400


def _named_source(conn, owner, name):
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    return str(SourcesRepository(conn).create(name, user_id=owner)["id"])


def _source_page(source_id):
    """A turn's stored sources pointing at ``source_id``, as a retriever saves them."""
    return [{"title": "Overview", "source": "docs/overview.md", "source_id": source_id, "text": "x"}]


def _share_with(conn, resource_type, resource_id, owner, member, level):
    import uuid

    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    team = str(TeamsRepository(conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)["id"])
    TeamMembersRepository(conn).add_member(team, member)
    TeamResourceGrantsRepository(conn).grant(team, resource_type, resource_id, owner, owner, access_level=level)


def _gap_names(app, pg_conn, user, body=None):
    """``(source group name, page group source line)`` of the docs gaps ``user`` reads."""
    body = body or {}
    by_source = _gaps(app, pg_conn, user, {**body, "group_by": "source"}).json["rows"]
    by_page = _gaps(app, pg_conn, user, {**body, "group_by": "page"}).json["rows"]
    assert len(by_source) == 1 and len(by_page) == 1
    return by_source[0]["name"], by_page[0]["source"]


class TestDocsGapsSourceNames:
    """A docs-gap row names its source only when the reader may use that source: the ids come from the turn's
    stored sources, which a chunk's own metadata can set, so another user's id must not read back as a name."""

    def test_another_users_private_source_is_not_named(self, app, pg_conn, analytics_on):
        private = _named_source(pg_conn, "victim-a", "Acme M&A due diligence")
        _labelled_conversation(pg_conn, "attacker-b", sources=_source_page(private), gap={"docs missing": 0.9})

        # the gap row stays, unnamed, as a deleted source's does
        assert _gap_names(app, pg_conn, "attacker-b") == (private, None)

    def test_own_source_is_named(self, app, pg_conn, analytics_on):
        mine = _named_source(pg_conn, "u-own", "Product docs")
        _labelled_conversation(pg_conn, "u-own", sources=_source_page(mine), gap={"docs missing": 0.9})

        assert _gap_names(app, pg_conn, "u-own") == ("Product docs", "Product docs")

    @pytest.mark.parametrize("level", ["viewer", "editor"])
    def test_team_shared_source_is_named(self, app, pg_conn, analytics_on, level):
        shared = _named_source(pg_conn, "alice", "Team handbook")
        _share_with(pg_conn, "source", shared, "alice", "bob", level)
        _labelled_conversation(pg_conn, "bob", sources=_source_page(shared), gap={"docs missing": 0.9})

        assert _gap_names(app, pg_conn, "bob") == ("Team handbook", "Team handbook")

    def test_agent_view_names_the_owners_sources_for_the_owner_and_its_editors(self, app, pg_conn, analytics_on):
        agent = str(_analytics_agent(pg_conn, owner="owner-a")["id"])
        _share_with(pg_conn, "agent", agent, "owner-a", "editor-e", "editor")
        owned = _named_source(pg_conn, "owner-a", "Owner docs")
        _labelled_conversation(pg_conn, "caller-b", agent_id=agent, sources=_source_page(owned),
                               gap={"docs missing": 0.9})

        for reader in ("owner-a", "editor-e"):
            assert _gap_names(app, pg_conn, reader, {"api_key_id": agent}) == ("Owner docs", "Owner docs")

    def test_agent_view_names_a_sponsored_source(self, app, pg_conn, analytics_on):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        # an editor's source the owner can't use, attached and sponsored by that editor
        sponsored = _named_source(pg_conn, "editor-e", "Editor research")
        agent = str(AgentsRepository(pg_conn).create(
            "owner-a", "Docs bot", "published", key="key-sponsored", config={"analytics": {}},
            extra_source_ids=[sponsored], resource_sponsors={f"source:{sponsored}": "editor-e"},
        )["id"])
        _labelled_conversation(pg_conn, "caller-b", agent_id=agent, sources=_source_page(sponsored),
                               gap={"docs missing": 0.9})

        assert _gap_names(app, pg_conn, "owner-a", {"api_key_id": agent}) == ("Editor research", "Editor research")

    def test_agent_view_does_not_name_a_source_the_agent_cannot_reach(self, app, pg_conn, analytics_on):
        private = _named_source(pg_conn, "victim-a", "Acme M&A due diligence")
        agent = str(_analytics_agent(pg_conn, owner="attacker-b")["id"])
        _labelled_conversation(pg_conn, "caller-c", agent_id=agent, sources=_source_page(private),
                               gap={"docs missing": 0.9})

        assert _gap_names(app, pg_conn, "attacker-b", {"api_key_id": agent}) == (private, None)


def _chat_log(conn, user, message_id, conversation_id, agent_id=None):
    from docsgpt.storage.db.repositories.user_logs import UserLogsRepository

    UserLogsRepository(conn).insert(
        user_id=user, endpoint="stream",
        data={"action": "stream_answer", "question": "q", "level": "info", "message_id": message_id,
              "conversation_id": conversation_id, "agent_id": agent_id},
    )


class TestLogsLabels:
    def _seed(self, pg_conn):
        agent = _analytics_agent(pg_conn)
        agent_id = str(agent["id"])
        declined = {"fully answered": 0.2, "declined, no information": 0.7, "not a request": 0.1}
        cid, first, second = _labelled_conversation(pg_conn, "owner", agent_id=agent_id,
                                                    gap={"docs missing": 0.6}, turn=declined)
        calm_cid, calm_first, calm_second = _labelled_conversation(pg_conn, "owner", agent_id=agent_id,
                                                                   frustrated=0.1)
        for message, conversation in ((first, cid), (second, cid), (calm_first, calm_cid),
                                      (calm_second, calm_cid)):
            _chat_log(pg_conn, "owner", message, conversation, agent_id)
        return agent_id, cid, first, second, calm_second

    def test_rows_carry_labels_and_tag_names(self, app, pg_conn, analytics_on):
        agent_id, _cid, first, second, calm_second = self._seed(pg_conn)
        data = _post_logs(app, pg_conn, "owner", {"api_key_id": agent_id, "event_type": "chat"}).json
        labels = {row["message_id"]: row["labels"] for row in data["logs"]}
        # docs gap and not fully answered on the turns; frustration on the reply that showed it; tags everywhere
        assert labels[first] == ["docs_gap", "not_answered", f"tag:{_TAG}"]
        assert labels[second] == ["docs_gap", "not_answered", "negative_reaction", "negative_sentiment", "frustrated",
                                  f"tag:{_TAG}"]
        assert labels[calm_second] == ["negative_reaction", "negative_sentiment", f"tag:{_TAG}"]
        assert data["tag_names"] == {_TAG: "Pricing question"}

    def test_label_filters(self, app, pg_conn):
        agent_id, cid, first, second, _calm_second = self._seed(pg_conn)

        def ids(body):
            response = _post_logs(app, pg_conn, "owner", {"api_key_id": agent_id, **body})
            assert response.status_code == 200
            return {row["message_id"] for row in response.json["logs"]}

        assert ids({"label": "frustrated"}) == {second}
        assert ids({"label": "docs_gap"}) == {first, second}
        assert ids({"label": "not_answered"}) == {first, second}
        assert len(ids({"label": "negative_reaction"})) == 2
        assert len(ids({"label": "negative_sentiment"})) == 2
        assert len(ids({"label": f"tag:{_TAG}"})) == 4
        assert ids({"label": "asks_human"}) == set()
        assert ids({"label": "frustrated", "conversation_id": cid}) == {second}
        assert ids({"label": "docs_gap", "conversation_id": cid}) == {first, second}
        assert ids({"conversation_id": cid}) == {first, second}
        assert ids({"label": "frustrated", "event_type": "schedule"}) == set()

    def test_topic_filter_matches_turns_about_the_topic(self, app, pg_conn):
        agent = _analytics_agent(pg_conn)
        agent_id = str(agent["id"])
        cid, first, second = _labelled_conversation(pg_conn, "owner", agent_id=agent_id,
                                                    topics={"install": 0.7, "auth": 0.3})
        other, other_first, other_second = _labelled_conversation(pg_conn, "owner", agent_id=agent_id,
                                                                  topics={"install": 0.4, "auth": 0.6})
        for message, conversation in ((first, cid), (second, cid), (other_first, other),
                                      (other_second, other)):
            _chat_log(pg_conn, "owner", message, conversation, agent_id)

        def ids(label):
            response = _post_logs(app, pg_conn, "owner", {"api_key_id": agent_id, "label": label})
            assert response.status_code == 200
            return {row["message_id"] for row in response.json["logs"]}

        assert ids("topic:install") == {first, second}
        assert ids("topic:auth") == {other_first, other_second}
        assert ids("topic:it's quoted") == set()

    def test_invalid_label_is_400(self, app, pg_conn):
        for label in ("bogus", "tag:UPPER123", "tag:", "topic:", "topic:" + "n" * 61, 5, ["frustrated"], {"a": 1}):
            response = _post_logs(app, pg_conn, "owner", {"label": label})
            assert response.status_code == 400

    def test_rows_without_labels_get_an_empty_list(self, app, pg_conn, analytics_on):
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository

        cid = str(ConversationsRepository(pg_conn).create("u-none", "c")["id"])
        message = _insert_message(pg_conn, cid, 0, "hi")
        _chat_log(pg_conn, "u-none", message, cid)
        data = _post_logs(app, pg_conn, "u-none", {}).json
        assert data["logs"][0]["labels"] == []
        assert data["tag_names"] == {}


class TestTopicFolders:
    def _get(self, app, pg_conn, user, agent_id):
        from docsgpt.api.user.analytics.routes import GetTopicFolders

        query = f"?agent_id={agent_id}" if agent_id else ""
        with _patch_analytics_db(pg_conn), app.test_request_context(
            f"/api/analytics/topic_folders{query}", method="GET"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return GetTopicFolders().get()

    def test_lists_the_folders_largest_first(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        structure = {"guides": {"setup.md": {"token_count": 10}, "deploy.md": {"token_count": 5}},
                     "api": {"auth.md": {"token_count": 3}}}
        source = SourcesRepository(pg_conn).create("Docs", user_id="owner", directory_structure=structure)
        agent = AgentsRepository(pg_conn).create("owner", "a", "published", source_id=str(source["id"]))
        response = self._get(app, pg_conn, "owner", str(agent["id"]))
        assert response.status_code == 200
        assert response.json == {"success": True, "folders": [
            {"name": "guides", "description": "Pages such as: Deploy; Setup"},
            {"name": "api", "description": "Pages such as: Auth"},
        ]}

    def test_needs_an_agent_the_caller_can_edit(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create("owner", "a", "published")
        assert self._get(app, pg_conn, "stranger", str(agent["id"])).status_code == 404
        assert self._get(app, pg_conn, "owner", None).status_code == 400


class TestAgentTopics:
    def _get(self, app, pg_conn, user, agent_id):
        from docsgpt.api.user.analytics.routes import GetAgentTopics

        query = f"?agent_id={agent_id}" if agent_id else ""
        with _patch_analytics_db(pg_conn), app.test_request_context(
            f"/api/analytics/topics{query}", method="GET"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return GetAgentTopics().get()

    def test_every_topic_with_its_logs_label_sorted_by_name(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        structure = {"guides": {"setup.md": {"token_count": 10}}, "api": {"auth.md": {"token_count": 3}},
                     "faq": {"q.md": {"token_count": 1}}}
        source = SourcesRepository(pg_conn).create("Docs", user_id="owner", directory_structure=structure)
        agent = AgentsRepository(pg_conn).create("owner", "a", "published", source_id=str(source["id"]), config={
            "analytics": {"hidden_folders": ["faq"], "topics": [
                {"id": _TAG, "name": "Pricing question", "overlap": True},
                {"id": "billing01", "name": "Billing"}]}})
        response = self._get(app, pg_conn, "owner", str(agent["id"]))
        assert response.status_code == 200
        assert response.json == {"success": True, "topics": [
            {"label": "topic:api", "name": "api", "overlap": False},
            {"label": "topic:Billing", "name": "Billing", "overlap": False},
            {"label": "topic:guides", "name": "guides", "overlap": False},
            {"label": f"tag:{_TAG}", "name": "Pricing question", "overlap": True},
        ]}

    def test_a_long_named_source_lists_a_label_the_logs_filter_takes(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        repo = SourcesRepository(pg_conn)
        flat = repo.create("Q3-2025 Vendor Due Diligence Questionnaire - Halvorsen Logistics (final, signed).pdf",
                           user_id="owner", directory_structure={"questionnaire.pdf": {"token_count": 900}})
        docs = repo.create("Docs", user_id="owner", directory_structure={"guides": {"setup.md": {"token_count": 9}}})
        agent = AgentsRepository(pg_conn).create("owner", "a", "published", key="key-long",
                                                 source_id=str(docs["id"]), extra_source_ids=[str(flat["id"])])
        agent_id = str(agent["id"])
        listed = self._get(app, pg_conn, "owner", agent_id).json["topics"]
        label = next(topic["label"] for topic in listed if topic["name"].startswith("q3-2025"))
        name = label.removeprefix("topic:")
        assert len(name) <= 60
        cid, first, second = _labelled_conversation(pg_conn, "owner", agent_id=agent_id,
                                                    topics={name: 0.8, "guides": 0.2})
        for message in (first, second):
            _chat_log(pg_conn, "owner", message, cid, agent_id)
        response = _post_logs(app, pg_conn, "owner", {"api_key_id": agent_id, "label": label})
        assert response.status_code == 200
        assert {row["message_id"] for row in response.json["logs"]} == {first, second}

    def test_needs_the_agents_logs(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create("owner", "a", "published")
        assert self._get(app, pg_conn, "stranger", str(agent["id"])).json == {"success": True, "topics": []}
        assert self._get(app, pg_conn, "owner", None).status_code == 400


class TestSharedAgentLabelVisibility:
    """Labels of a shared agent's conversations are written under its owner's topics and sources; a caller's own
    (account) views must not hand those names back, while the owner's per-agent views still show them."""

    _OWN = "Secret roadmap"
    _OVERLAP = "Acquisition talks"
    _SOURCE = "Confidential handbook"

    def _seed(self, pg_conn, *, user="caller-b"):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        source = SourcesRepository(pg_conn).create(self._SOURCE, user_id="owner-a")
        agent = _analytics_agent(pg_conn, owner="owner-a", topics=[
            {"id": "roadmap01", "name": self._OWN},
            {"id": _TAG, "name": self._OVERLAP, "overlap": True}])
        agent_id = str(agent["id"])
        stored = [{"title": "Plans", "source": "internal/plans.md", "source_id": str(source["id"]), "text": "x"}]
        cid, first, second = _labelled_conversation(
            pg_conn, user, agent_id=agent_id, sources=stored, gap={"docs missing": 0.9},
            topics={self._OWN: 0.9, "none of these": 0.1})
        for message in (first, second):
            _chat_log(pg_conn, user, message, cid, agent_id)
        return agent_id, cid, first, second

    def _names(self, payload) -> str:
        import json

        return json.dumps(payload)

    def test_a_caller_sees_none_of_the_owners_names(self, app, pg_conn, analytics_on):
        self._seed(pg_conn)
        for group_by in ("topic", "source", "page"):
            data = _gaps(app, pg_conn, "caller-b", {"group_by": group_by}).json
            assert data["rows"] == [], group_by
        logs = _post_logs(app, pg_conn, "caller-b", {"event_type": "chat"}).json
        assert len(logs["logs"]) == 2
        assert all(row["labels"] == [] for row in logs["logs"])
        assert logs["tag_names"] == {}
        text = self._names(logs)
        assert self._OVERLAP not in text and self._SOURCE not in text
        totals = _insights(app, pg_conn, "caller-b", {}).json
        assert totals["totals"]["frustrated"]["n"] == 0
        assert totals["coverage"]["labelled_turns"] == totals["coverage"]["turns"] == 0

    def test_the_label_filter_is_no_topic_oracle(self, app, pg_conn, analytics_on):
        self._seed(pg_conn)
        for label in (f"topic:{self._OWN}", f"tag:{_TAG}", "docs_gap", "frustrated"):
            data = _post_logs(app, pg_conn, "caller-b", {"label": label}).json
            assert data["logs"] == [], label

    def test_the_owner_still_sees_them_on_the_agent(self, app, pg_conn, analytics_on):
        agent_id, _cid, first, second = self._seed(pg_conn)
        topics = _gaps(app, pg_conn, "owner-a", {"api_key_id": agent_id, "group_by": "topic"}).json
        assert [row["key"] for row in topics["rows"]] == [self._OWN]
        sources = _gaps(app, pg_conn, "owner-a", {"api_key_id": agent_id, "group_by": "source"}).json
        assert [row["name"] for row in sources["rows"]] == [self._SOURCE]
        pages = _gaps(app, pg_conn, "owner-a", {"api_key_id": agent_id, "group_by": "page"}).json
        assert [row["source"] for row in pages["rows"]] == [self._SOURCE]
        logs = _post_logs(app, pg_conn, "owner-a", {"api_key_id": agent_id, "event_type": "chat"}).json
        assert {row["message_id"] for row in logs["logs"] if f"tag:{_TAG}" in row["labels"]} == {first, second}
        assert logs["tag_names"] == {_TAG: self._OVERLAP}
        found = _post_logs(app, pg_conn, "owner-a", {"api_key_id": agent_id, "label": f"topic:{self._OWN}"}).json
        assert {row["message_id"] for row in found["logs"]} == {first, second}

    def test_a_deleted_agents_conversations_leave_account_coverage_with_their_labels(self, app, pg_conn,
                                                                                      analytics_on):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        agent_id, _cid, _first, _second = self._seed(pg_conn)
        own = _labelled_conversation(pg_conn, "caller-b")
        AgentsRepository(pg_conn).delete(agent_id, "owner-a")
        data = _insights(app, pg_conn, "caller-b", {}).json
        # the deleted agent's labels stay hidden, so its turns are neither counted nor labelled; the caller's own
        # conversation still is
        assert own
        assert data["coverage"]["turns"] == data["coverage"]["labelled_turns"] == 2
        assert data["coverage"]["conversations"] == data["coverage"]["labelled_conversations"] == 1
        assert data["coverage"]["replies"] == data["coverage"]["labelled_replies"] == 1
        assert data["coverage"]["unlabelled_recent_turns"] == 0
        assert data["totals"]["answer_status"]["n"] == 2

    def test_a_callers_own_agent_logs_show_none_of_the_owners_names(self, app, pg_conn, analytics_on):
        # A turn naming the caller's own agent, sent into their conversation with the owner's agent, logs under
        # the caller's agent; that agent's Logs must not read labels written under the owner's agent.
        own = str(_analytics_agent(pg_conn, owner="caller-b", topics=[])["id"])
        _agent_id, cid, first, second = self._seed(pg_conn)
        for message in (first, second):
            _chat_log(pg_conn, "caller-b", message, cid, own)
        logs = _post_logs(app, pg_conn, "caller-b", {"api_key_id": own, "event_type": "chat"}).json
        assert {row["message_id"] for row in logs["logs"]} >= {first, second}
        assert all(row["labels"] == [] for row in logs["logs"])
        assert logs["tag_names"] == {}
        assert self._OVERLAP not in self._names(logs)
        for label in (f"topic:{self._OWN}", f"tag:{_TAG}", "frustrated"):
            found = _post_logs(app, pg_conn, "caller-b", {"api_key_id": own, "label": label}).json
            assert found["logs"] == [], label

    def test_the_owner_sees_their_own_chats_with_their_agent_in_the_account_view(self, app, pg_conn,
                                                                                 analytics_on):
        _agent_id, _cid, first, second = self._seed(pg_conn, user="owner-a")
        topics = _gaps(app, pg_conn, "owner-a", {"group_by": "topic"}).json
        assert [row["key"] for row in topics["rows"]] == [self._OWN]
        logs = _post_logs(app, pg_conn, "owner-a", {"event_type": "chat"}).json
        assert all(f"tag:{_TAG}" in row["labels"] for row in logs["logs"])
        assert logs["tag_names"] == {_TAG: self._OVERLAP}
        found = _post_logs(app, pg_conn, "owner-a", {"label": f"topic:{self._OWN}"}).json
        assert {row["message_id"] for row in found["logs"]} == {first, second}
        assert _insights(app, pg_conn, "owner-a", {}).json["totals"]["frustrated"]["n"] == 1


class TestLabelsFollowTheServerSwitch:
    def test_logs_carry_no_label_chips_while_insights_are_off(self, app, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.storage.db.repositories.conversation_labels import ConversationLabelsRepository

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        agent_id, _cid, first, second, _calm = TestLogsLabels()._seed(pg_conn)

        def no_lookup(*_args, **_kwargs):
            raise AssertionError("label rows were read with insights off")

        monkeypatch.setattr(ConversationLabelsRepository, "log_rows", no_lookup)
        data = _post_logs(app, pg_conn, "owner", {"api_key_id": agent_id, "event_type": "chat"}).json
        assert data["logs"] and all("labels" not in row for row in data["logs"])
        assert data["tag_names"] == {}
        # the filter still works, for a link that carries a label
        monkeypatch.undo()
        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        found = _post_logs(app, pg_conn, "owner", {"api_key_id": agent_id, "label": "frustrated"}).json
        assert {row["message_id"] for row in found["logs"]} == {second}

    def test_insights_read_no_topic_list_while_off(self, app, pg_conn, analytics_on, monkeypatch):
        from docsgpt.core.settings import settings

        agent = _analytics_agent(pg_conn, topics=[{"id": "billing01", "name": "Billing"}])

        calls = []
        monkeypatch.setattr("docsgpt.analytics.topics.options", lambda *args, **kwargs: calls.append(args) or [])
        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        data = _insights(app, pg_conn, "owner", {"api_key_id": str(agent["id"])}).json
        assert (data["enabled"], data["one_pick"]) == (False, [])
        off = _analytics_agent(pg_conn, owner="owner-off", enabled=False)
        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
        assert _insights(app, pg_conn, "owner-off", {"api_key_id": str(off["id"])}).json["one_pick"] == []
        # the agent's sources are read only once the agent's insights are on
        assert calls == []
