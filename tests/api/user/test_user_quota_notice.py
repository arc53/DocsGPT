"""``GET /api/user/quota``: the 80% notice, the parts of the caller's use, and what their stop pauses.

Driven through the real app.py chokepoint against real Postgres; only ``handle_auth`` / ``resolve_roles`` are
patched, and the modules' sessions are pointed at the per-test ``pg_conn``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from docsgpt.quotas.windows import window_bounds
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with ExitStack() as stack:
        for target in ("docsgpt.quotas.service.db_readonly", "docsgpt.api.user.me.routes.db_readonly"):
            stack.enter_context(patch(target, _yield))
        yield pg_conn


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _quota(client, user="dana"):
    with _as(user):
        resp = client.get("/api/user/quota")
    assert resp.status_code == 200, resp.data
    return json.loads(resp.data)


def _limit(conn, user="dana", tokens=None, cost=None, bucket="all"):
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user, bucket=bucket, token_limit=tokens,
                                         cost_limit_usd=cost)


def _spend(conn, tokens, kind=None, user="dana", cost=0.0):
    TokenUsageRepository(conn).insert(user_id=user, prompt_tokens=tokens, run_kind=kind, cost=cost)


class TestNotice:
    def test_none_under_80_percent(self, client, db):
        _limit(db, tokens=100)
        _spend(db, 79)
        body = _quota(client)
        assert body["notice"] is None
        assert body["paused"] is None

    def test_near_from_80_percent(self, client, db):
        _limit(db, tokens=100)
        _spend(db, 80)
        _, resets = window_bounds("month")
        assert _quota(client)["notice"] == {
            "level": "near", "percent": 80, "bucket": "all", "budget": "tokens", "resets_at": resets.isoformat(),
        }

    def test_the_highest_budget_over_every_bucket_wins(self, client, db):
        _limit(db, tokens=1000)
        _limit(db, cost=1.0, bucket="direct")
        _spend(db, 100, kind="chat", cost=0.9)
        notice = _quota(client)["notice"]
        assert notice["level"] == "near" and notice["bucket"] == "direct" and notice["budget"] == "cost"
        assert notice["percent"] == 90

    def test_reached_at_100_percent_with_what_it_pauses(self, client, db):
        _limit(db, tokens=100)
        _spend(db, 120, kind="chat")
        mine = str(AgentsRepository(db).create("dana", "Mine", "published")["id"])
        published = str(AgentsRepository(db).create(
            "dana", "Tender helper", "published", key=f"k-{uuid.uuid4().hex}",
            shared=True, shared_token=f"s-{uuid.uuid4().hex}",
        )["id"])
        SchedulesRepository(db).create("dana", mine, "recurring", "One", cron="0 9 * * *")
        SchedulesRepository(db).create("dana", mine, "recurring", "Two", cron="0 9 * * *")
        SchedulesRepository(db).create("dana", mine, "recurring", "Off", cron="0 9 * * *", status="paused")
        SchedulesRepository(db).create("someone", mine, "recurring", "Not hers", cron="0 9 * * *")
        body = _quota(client)
        assert body["notice"]["level"] == "reached" and body["notice"]["percent"] == 100
        assert body["paused"] == {
            "schedules": 2,
            "published": [{"agent_id": published, "name": "Tender helper", "access": ["api_key", "public_link"]}],
        }

    def test_reached_lists_team_agents_the_caller_pays_for(self, client, db):
        team = TeamsRepository(db).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "lena")
        tid = str(team["id"])
        TeamMembersRepository(db).add_member(tid, "lena", role="team_admin")
        TeamMembersRepository(db).add_member(tid, "dana", role="team_admin")
        agent = str(AgentsRepository(db).create(
            principal_id(tid), "Carrier desk", "published", incoming_webhook_token=f"w-{uuid.uuid4().hex}",
            access_payer_id="dana",
        )["id"])
        AgentsRepository(db).create(
            principal_id(tid), "Lena pays", "published", key=f"k-{uuid.uuid4().hex}", access_payer_id="lena",
        )
        _limit(db, tokens=10)
        _spend(db, 10)
        assert _quota(client)["paused"]["published"] == [
            {"agent_id": agent, "name": "Carrier desk", "access": ["webhook"]}
        ]


class TestParts:
    def test_parts_by_run_kind(self, client, db):
        _limit(db, tokens=10_000)
        _spend(db, 10, kind="chat", cost=0.1)
        _spend(db, 5, kind="drafter")
        _spend(db, 20, kind="schedule")
        _spend(db, 3, kind="monitor")
        _spend(db, 40, kind="published")
        _spend(db, 7, kind="knowledge")
        _spend(db, 1, kind=None)
        _spend(db, 999, kind="chat", user="someone")
        assert _quota(client)["parts"] == [
            {"kind": "chat", "tokens": 15, "cost": 0.1},
            {"kind": "schedule", "tokens": 23, "cost": 0.0},
            {"kind": "published", "tokens": 40, "cost": 0.0},
            {"kind": "other", "tokens": 8, "cost": 0.0},
        ]


class TestUnlimited:
    def test_gets_neither_and_costs_no_usage_query(self, client, db):
        _spend(db, 10_000, kind="chat")
        with patch.object(TokenUsageRepository, "usage_totals") as totals, patch.object(
            TokenUsageRepository, "usage_by_kind"
        ) as by_kind:
            body = _quota(client)
        assert body == {"success": True, "period": "month", "buckets": [], "notice": None, "parts": None,
                        "paused": None}
        totals.assert_not_called()
        by_kind.assert_not_called()

    def test_a_parts_failure_still_answers_the_buckets(self, client, db):
        _limit(db, tokens=100)
        _spend(db, 10)
        with patch.object(TokenUsageRepository, "usage_by_kind", side_effect=RuntimeError("down")):
            body = _quota(client)
        assert body["buckets"][0]["tokens"] == {"limit": 100, "used": 10}
        assert body["parts"] is None
