"""Payer fields on team payloads: the share dialog's paused outside access, and ``chat_export`` on workspace rows.

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
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.repositories.users import UsersRepository
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
        for target in (
            "docsgpt.api.user.teams.routes.db_readonly",
            "docsgpt.api.user.teams.routes.db_session",
            "docsgpt.api.user.team_authz.db_readonly",
            "docsgpt.api.user.workspaces.routes.db_readonly",
            "docsgpt.quotas.service.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        yield pg_conn


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _team(conn):
    users = UsersRepository(conn)
    for user in ("lena", "jonas", "dana", "tomas"):
        users.upsert(user, email=f"{user}@x.io")
    tid = str(TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "lena")["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "lena", role="team_admin")
    repo.add_member(tid, "jonas", role="team_admin")
    repo.add_member(tid, "dana", role="team_editor")
    repo.add_member(tid, "tomas", role="team_viewer")
    return tid


def _published(conn, tid, payer):
    return str(AgentsRepository(conn).create(
        principal_id(tid), "Desk", "published", key=f"k-{uuid.uuid4().hex}", access_payer_id=payer,
    )["id"])


def _outside(client, aid, user):
    with _as(user):
        resp = client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}")
    assert resp.status_code == 200, resp.data
    return json.loads(resp.data)["outside_access"]


class TestShareDialogPause:
    def test_running_access_is_not_paused_and_another_admin_may_take_over(self, client, db):
        tid = _team(db)
        aid = _published(db, tid, "jonas")
        outside = _outside(client, aid, "lena")
        assert outside["paused_for"] is None
        assert outside["can_take_over"] is True

    def test_the_payer_cannot_take_over_from_themselves(self, client, db):
        tid = _team(db)
        aid = _published(db, tid, "jonas")
        assert _outside(client, aid, "jonas")["can_take_over"] is False

    @pytest.mark.parametrize("user", ["dana", "tomas"])
    def test_below_admin_may_not_take_over(self, client, db, user):
        tid = _team(db)
        aid = _published(db, tid, "jonas")
        assert _outside(client, aid, user)["can_take_over"] is False

    def test_a_payer_below_admin_reads_payer_left(self, client, db):
        tid = _team(db)
        aid = _published(db, tid, "dana")
        outside = _outside(client, aid, "lena")
        assert outside["paused_for"] == {"reason": "payer_left", "until": None}
        assert outside["can_take_over"] is True

    def test_no_payer(self, client, db):
        tid = _team(db)
        aid = _published(db, tid, None)
        outside = _outside(client, aid, "lena")
        assert outside["paused_for"] == {"reason": "no_payer", "until": None}
        assert outside["paid_by"] is None and outside["can_take_over"] is True

    def test_a_payer_out_of_allowance(self, client, db):
        tid = _team(db)
        aid = _published(db, tid, "jonas")
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="jonas", token_limit=10)
        TokenUsageRepository(db).insert(user_id="jonas", prompt_tokens=20)
        _, resets = window_bounds("month")
        assert _outside(client, aid, "lena")["paused_for"] == {
            "reason": "payer_out_of_allowance", "until": resets.isoformat(),
        }

    @pytest.mark.parametrize("user", ["dana", "tomas"])
    def test_below_admin_reads_what_is_on_but_not_who_pays_or_why_it_is_paused(self, client, db, user):
        tid = _team(db)
        aid = _published(db, tid, "jonas")
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="jonas", token_limit=10)
        TokenUsageRepository(db).insert(user_id="jonas", prompt_tokens=20)

        assert _outside(client, aid, user) == {
            "api_key": True, "public_link": False, "webhook": False, "paid_by": None, "paused_for": None,
            "can_take_over": False,
        }

    @pytest.mark.parametrize("user", ["lena", "dana", "tomas"])
    def test_the_dialog_names_the_team(self, client, db, user):
        tid = _team(db)
        aid = _published(db, tid, "jonas")
        with _as(user):
            body = json.loads(client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}").data)

        assert body["workspace"] == {"kind": "team", "team_id": tid, "name": "Ops"}

    def test_nothing_on_is_never_paused(self, client, db):
        tid = _team(db)
        aid = str(AgentsRepository(db).create(principal_id(tid), "Quiet", "published")["id"])
        outside = _outside(client, aid, "lena")
        assert outside["paused_for"] is None and outside["can_take_over"] is False


class TestShareDialogUsesTheAgentPayloadRule:
    """The share dialog's ``outside_access`` comes from the same helper as the agent payload's, so they can't drift."""

    def test_the_dialog_returns_the_agent_payloads_block(self, client, db):
        tid = _team(db)
        aid = _published(db, tid, "jonas")
        marker = {"from": "outside_access_state"}
        seen = []

        def _state(conn, agent, ra, user, *, checks=None):
            seen.append((str(agent["id"]), ra.resource_id, user))
            return marker

        with patch("docsgpt.api.user.agents.sharing.outside_access_state", _state):
            assert _outside(client, aid, "lena") == marker
        assert seen == [(aid, aid, "lena")]

    @pytest.mark.parametrize("payer,user", [("jonas", "lena"), ("jonas", "jonas"), ("dana", "tomas"), (None, "lena")])
    def test_the_dialog_matches_the_helper_for_each_reader(self, client, db, payer, user):
        from docsgpt.api.user.agents.sharing import outside_access_state
        from docsgpt.api.user.resource_access import resolve

        tid = _team(db)
        aid = _published(db, tid, payer)
        expected = outside_access_state(
            db, AgentsRepository(db).get_by_id(aid), resolve(db, "agent", aid, user), user,
        )
        assert _outside(client, aid, user) == json.loads(json.dumps(expected))


class TestWorkspaceRows:
    def _rows(self, client, user="tomas"):
        with _as(user):
            resp = client.get("/api/workspaces")
        assert resp.status_code == 200
        return json.loads(resp.data)["workspaces"]

    @pytest.mark.parametrize("on", [True, False])
    def test_team_rows_carry_the_export_setting(self, client, db, on):
        _team(db)
        with patch("docsgpt.api.user.workspaces.routes.settings.TEAM_CHAT_EXPORT_ENABLED", on):
            personal, team = self._rows(client)
        assert "chat_export" not in personal
        assert team["chat_export"] is on
