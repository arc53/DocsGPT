"""Tests for quota enforcement at the request entry points."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.quotas.service import QuotaExceededError
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with patch("docsgpt.quotas.service.db_readonly", _yield), patch(
        "docsgpt.api.answer.routes.base.db_readonly", _yield
    ), patch("docsgpt.agents.headless_runner.db_readonly", _yield):
        yield pg_conn


def _spend(conn, user_id, tokens, api_key=None):
    TokenUsageRepository(conn).insert(user_id=user_id, api_key=api_key, prompt_tokens=tokens)


def _check(flask_app, agent_config, decoded_token=None):
    from docsgpt.api.answer.routes.base import BaseAnswerResource

    with flask_app.app_context():
        return BaseAnswerResource().check_usage(agent_config, decoded_token)


class TestCheckUsage:
    def test_direct_chat_is_limited(self, db, flask_app):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u1", token_limit=100)
        _spend(db, "u1", 100)

        response = _check(flask_app, {}, {"sub": "u1"})

        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) >= 1
        body = json.loads(response.data)
        assert body["error_code"] == "quota-exceeded"
        assert (body["dimension"], body["usage"], body["limit"], body["source"]) == ("tokens", 100, 100, "user")

    def test_direct_chat_under_the_limit_passes(self, db, flask_app):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u1", token_limit=100)
        _spend(db, "u1", 99)
        assert _check(flask_app, {}, {"sub": "u1"}) is None

    def test_no_policies_and_no_identity_pass(self, db, flask_app):
        assert _check(flask_app, {}) is None
        assert _check(flask_app, {}, {"sub": "u1"}) is None

    def test_agent_traffic_bills_the_resolved_user(self, db, flask_app):
        AgentsRepository(db).create("owner", "a", "published", key="k1")
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="owner", token_limit=10)
        _spend(db, "owner", 10, api_key="k1")

        config = {"user_api_key": "k1", "user_id": "owner"}
        assert _check(flask_app, config, {"sub": "owner"}).status_code == 429
        # A shared agent bills the caller, who has room.
        assert _check(flask_app, config, {"sub": "caller"}) is None
        # No token resolved: fall back to the agent owner.
        assert _check(flask_app, config).status_code == 429

    def test_quota_runs_before_the_agent_key_lookup(self, db, flask_app):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u1", token_limit=0)
        response = _check(flask_app, {"user_api_key": "missing"}, {"sub": "u1"})
        assert response.status_code == 429

    def test_agent_limits_still_apply(self, db, flask_app):
        AgentsRepository(db).create(
            "owner", "a", "published", key="k2", limited_token_mode=True, token_limit=5
        )
        _spend(db, "owner", 5, api_key="k2")
        response = _check(flask_app, {"user_api_key": "k2"}, {"sub": "owner"})
        assert response.status_code == 429
        assert "error_code" not in json.loads(response.data)

    def test_agent_bucket_policy_ignores_direct_chat(self, db, flask_app):
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u1", bucket="agent", token_limit=10)
        _spend(db, "u1", 500)
        assert _check(flask_app, {}, {"sub": "u1"}) is None


class TestHeadless:
    def test_exhausted_owner_is_refused_before_the_run(self, db):
        from docsgpt.agents.headless_runner import run_agent_headless

        QuotaPoliciesRepository(db).upsert(scope="instance", subject_id=None, token_limit=10)
        _spend(db, "owner", 10)

        with patch("docsgpt.agents.headless_runner.RetrieverCreator") as retriever:
            with pytest.raises(QuotaExceededError) as raised:
                run_agent_headless({"user_id": "owner", "key": "k"}, "hello")

        retriever.create_retriever.assert_not_called()
        assert raised.value.exceeded.source == "instance"
        assert "10 of 10 tokens" in str(raised.value)

