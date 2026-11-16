"""Taking over a team agent's outside access, and the ``outside_access`` block ``get_agent`` returns.

An Admin of the team may become the person who pays for the agent's key, public link and webhook
(``POST /api/agents/<id>/outside_access/take_over``), which resumes access paused because its payer left or
lost the role. The write is bookkeeping (``updated_at`` stays), audited once per real change, and refused to
Editors, on a personal agent, with nothing switched on, and to tokens. ``get_agent`` shows the block, with who
pays, why it is paused and whether the reader may take over, to those who manage access details.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.owner_pause import outside_access_refusal
from docsgpt.quotas.service import QuotaExceeded, QuotaService
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

TAKE_OVER = "/api/agents/<string:agent_id>/outside_access/take_over"
RESETS_AT = datetime(2026, 12, 1, tzinfo=timezone.utc)

_DB_MODULES = ("docsgpt.api.user.agents.routes", "docsgpt.api.user.agents.sharing")


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def quota(monkeypatch):
    """Who is out of allowance (QuotaService.check), by person."""
    out: set[str] = set()

    def _check(cls, user_id, bucket="all", now=None):
        if user_id not in out:
            return None
        return QuotaExceeded(
            user_id=user_id, bucket=bucket, budget="tokens", usage=10, limit=10, source=None, source_id=None,
            resets_at=RESETS_AT,
        )

    monkeypatch.setattr(QuotaService, "check", classmethod(_check))
    return out


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for module in _DB_MODULES:
            for attr in ("db_session", "db_readonly"):
                stack.enter_context(patch(f"{module}.{attr}", _yield))
        yield


def _call(app, conn, method, path, user, *, args=(), query=None):
    from docsgpt.api.user.agents.routes import GetAgent
    from docsgpt.api.user.agents.sharing import TakeOverOutsideAccess

    resource = TakeOverOutsideAccess if "take_over" in path else GetAgent
    kwargs = {"method": method.upper()}
    if query is not None:
        kwargs["query_string"] = query
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        resp = getattr(resource(), method.lower())(*args)
    if isinstance(resp, tuple):
        return resp[1], resp[0]
    return resp.status_code, resp.get_json()


def _take_over(app, conn, agent_id, user):
    return _call(app, conn, "post", f"/api/agents/{agent_id}/outside_access/take_over", user, args=(agent_id,))


def _get_agent(app, conn, agent_id, user):
    return _call(app, conn, "get", "/api/get_agent", user, query={"id": agent_id})


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "jonas", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    repo.add_member(tid, "vera", role="team_viewer")
    return tid, principal_id(tid)


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _agent(conn, owner, *, payer="adam", key=True, link=True, webhook=True):
    suffix = uuid.uuid4().hex[:8]
    return AgentsRepository(conn).create(
        owner, "Desk", "published", key=f"k-{suffix}" if key else None, shared=link,
        shared_token=f"tok-{suffix}" if link else None, incoming_webhook_token=f"wh-{suffix}" if webhook else None,
        access_payer_id=payer, created_by="alice", default_model_id="m", agent_type="classic",
    )


def _row(conn, agent):
    return AgentsRepository(conn).get_by_id(str(agent["id"]))


def _audits(conn):
    rows = conn.execute(
        text("SELECT actor_id, metadata::text FROM auth_events WHERE event = 'team.outside_access_taken_over'")
    ).fetchall()
    return [(actor, json.loads(meta)) for actor, meta in rows]


class TestTakeOver:
    def test_an_admin_becomes_the_payer_and_it_is_audited(self, app, pg_conn, quota):
        tid, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer="adam")
        before = _row(pg_conn, agent)["updated_at"]

        status, body = _take_over(app, pg_conn, str(agent["id"]), "jonas")

        assert status == 200 and body["success"] is True and body["changed"] is True
        after = _row(pg_conn, agent)
        assert after["access_payer_id"] == "jonas"
        assert after["updated_at"] == before
        assert body["outside_access"]["paid_by"]["user_id"] == "jonas"
        assert body["outside_access"]["can_take_over"] is False
        assert _audits(pg_conn) == [(
            "jonas",
            {"team_id": tid, "agent_id": str(agent["id"]), "from": "adam", "to": "jonas",
             "access": ["api_key", "public_link", "webhook"]},
        )]

    def test_the_audit_names_only_what_is_switched_on(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, link=False, webhook=False)

        assert _take_over(app, pg_conn, str(agent["id"]), "jonas")[0] == 200
        assert _audits(pg_conn)[0][1]["access"] == ["api_key"]

    def test_the_team_owner_may_take_over(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal)

        assert _take_over(app, pg_conn, str(agent["id"]), "alice")[0] == 200
        assert _row(pg_conn, agent)["access_payer_id"] == "alice"

    def test_a_repeat_changes_nothing_and_audits_nothing(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal)
        _take_over(app, pg_conn, str(agent["id"]), "jonas")

        status, body = _take_over(app, pg_conn, str(agent["id"]), "jonas")

        assert status == 200 and body["changed"] is False
        assert len(_audits(pg_conn)) == 1

    def test_the_current_payer_taking_over_changes_nothing(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer="adam")

        status, body = _take_over(app, pg_conn, str(agent["id"]), "adam")

        assert status == 200 and body["changed"] is False and _audits(pg_conn) == []

    @pytest.mark.parametrize("user", ["eddie", "vera"])
    def test_below_admin_is_403(self, app, pg_conn, quota, user):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal)

        status, body = _take_over(app, pg_conn, str(agent["id"]), user)

        assert status == 403 and body == {
            "success": False, "error": "workspace_role_required", "message": body["message"],
        }
        assert _row(pg_conn, agent)["access_payer_id"] == "adam" and _audits(pg_conn) == []

    def test_someone_outside_the_team_gets_404(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal)

        status, body = _take_over(app, pg_conn, str(agent["id"]), "stranger")

        assert status == 404 and body["error"] == "agent_not_found"

    def test_an_unknown_agent_is_404(self, app, pg_conn, quota):
        status, body = _take_over(app, pg_conn, str(uuid.uuid4()), "jonas")
        assert status == 404 and body["error"] == "agent_not_found"

    def test_no_caller_is_401(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal)
        assert _take_over(app, pg_conn, str(agent["id"]), None)[0] == 401

    def test_a_personal_agent_is_409(self, app, pg_conn, quota):
        agent = _agent(pg_conn, "lena", payer=None)

        status, body = _take_over(app, pg_conn, str(agent["id"]), "lena")

        assert status == 409 and body["error"] == "take_over_team_only"
        assert _row(pg_conn, agent)["access_payer_id"] is None

    def test_nothing_switched_on_is_409(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer=None, key=False, link=False, webhook=False)

        status, body = _take_over(app, pg_conn, str(agent["id"]), "jonas")

        assert status == 409 and body["error"] == "no_outside_access"
        assert _row(pg_conn, agent)["access_payer_id"] is None

    def test_a_caller_out_of_allowance_may_take_over_and_then_shows_their_own_pause(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal)
        quota.add("jonas")

        status, body = _take_over(app, pg_conn, str(agent["id"]), "jonas")

        assert status == 200
        assert body["outside_access"]["paused_for"] == {"reason": "payer_out_of_allowance",
                                                       "until": RESETS_AT.isoformat()}

    @pytest.mark.parametrize("role", ["team_editor", None])
    def test_after_a_take_over_the_paused_agent_answers(self, app, pg_conn, quota, role):
        tid, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer="adam")
        _set_role(pg_conn, tid, "adam", role)
        assert outside_access_refusal(pg_conn, _row(pg_conn, agent)) is not None

        assert _take_over(app, pg_conn, str(agent["id"]), "jonas")[0] == 200

        assert outside_access_refusal(pg_conn, _row(pg_conn, agent)) is None

    def test_a_team_agent_with_no_payer_is_taken_over_from_nobody(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer=None)

        status, body = _take_over(app, pg_conn, str(agent["id"]), "jonas")

        assert status == 200 and body["changed"] is True
        assert "from" not in _audits(pg_conn)[0][1]
        assert outside_access_refusal(pg_conn, _row(pg_conn, agent)) is None


class TestTokensCannotTakeOver:
    def test_the_route_is_denied_to_tokens(self):
        from docsgpt.api.pat import rules

        assert rules.is_denied(TAKE_OVER, "POST")

    def test_a_token_request_is_refused_at_the_chokepoint(self):
        from docsgpt.api.pat.tokens import SCOPES, expand_scopes
        from docsgpt.app import app as flask_app

        claims = {
            "sub": "alice", "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
            "scopes": sorted(expand_scopes(list(SCOPES))), "resource_filter": {},
        }
        with patch("docsgpt.app.handle_auth", return_value=claims):
            response = flask_app.test_client().post(f"/api/agents/{uuid.uuid4()}/outside_access/take_over")
        assert response.status_code == 403
        assert response.get_json()["error"] == "not_available_to_tokens"


class TestGetAgentOutsideAccess:
    def test_an_admin_who_is_not_the_payer_may_take_over(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        UsersRepository(pg_conn).upsert("adam")
        pg_conn.execute(text("UPDATE users SET email = 'adam@ops.test' WHERE user_id = 'adam'"))
        agent = _agent(pg_conn, principal, payer="adam")

        status, body = _get_agent(app, pg_conn, str(agent["id"]), "jonas")

        assert status == 200
        assert body["outside_access"] == {
            "api_key": True, "public_link": True, "webhook": True,
            "paid_by": {"user_id": "adam", "label": "adam@ops.test"},
            "paused_for": None, "can_take_over": True,
        }

    def test_the_payer_may_not_take_over_from_themselves(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer="adam")

        body = _get_agent(app, pg_conn, str(agent["id"]), "adam")[1]

        assert body["outside_access"]["can_take_over"] is False
        assert body["outside_access"]["paid_by"] == {"user_id": "adam", "label": "adam"}

    @pytest.mark.parametrize("user", ["eddie", "vera"])
    def test_below_admin_gets_no_block(self, app, pg_conn, quota, user):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal)

        status, body = _get_agent(app, pg_conn, str(agent["id"]), user)

        assert status == 200 and "outside_access" not in body
        assert "owner_inactive" in body

    def test_with_nothing_on_nobody_pays_and_nothing_is_paused(self, app, pg_conn, quota):
        _, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer="adam", key=False, link=False, webhook=False)

        block = _get_agent(app, pg_conn, str(agent["id"]), "jonas")[1]["outside_access"]

        assert block == {
            "api_key": False, "public_link": False, "webhook": False,
            "paid_by": None, "paused_for": None, "can_take_over": False,
        }

    @pytest.mark.parametrize(
        "setup, reason, until",
        [
            ("deactivated", "owner_inactive", None),
            ("left", "payer_left", None),
            ("demoted", "payer_left", None),
            ("nobody", "no_payer", None),
            ("allowance", "payer_out_of_allowance", RESETS_AT.isoformat()),
        ],
    )
    def test_paused_for_each_reason(self, app, pg_conn, quota, setup, reason, until):
        tid, principal = _team(pg_conn)
        agent = _agent(pg_conn, principal, payer=None if setup == "nobody" else "adam")
        if setup == "deactivated":
            UsersRepository(pg_conn).upsert("adam")
            pg_conn.execute(text("UPDATE users SET active = false WHERE user_id = 'adam'"))
        elif setup == "left":
            _set_role(pg_conn, tid, "adam", None)
        elif setup == "demoted":
            _set_role(pg_conn, tid, "adam", "team_editor")
        elif setup == "allowance":
            quota.add("adam")

        block = _get_agent(app, pg_conn, str(agent["id"]), "jonas")[1]["outside_access"]

        expected = {"reason": reason, "until": until}
        if reason == "payer_left":
            # A team payer's pause says whether they left the team or only lost the role that pays.
            expected["left_team"] = setup == "left"
        assert block["paused_for"] == expected
        assert block["can_take_over"] is True

    def test_a_personal_agent_names_no_payer_and_offers_no_take_over(self, app, pg_conn, quota):
        agent = _agent(pg_conn, "lena", payer=None)

        status, body = _get_agent(app, pg_conn, str(agent["id"]), "lena")

        assert status == 200
        assert body["outside_access"] == {
            "api_key": True, "public_link": True, "webhook": True,
            "paid_by": None, "paused_for": None, "can_take_over": False,
        }

    def test_a_personal_agent_pauses_for_its_owners_allowance_never_payer_left(self, app, pg_conn, quota):
        tid, _ = _team(pg_conn)
        agent = _agent(pg_conn, "eddie", payer=None)
        _set_role(pg_conn, tid, "eddie", None)
        quota.add("eddie")

        block = _get_agent(app, pg_conn, str(agent["id"]), "eddie")[1]["outside_access"]

        assert block["paused_for"] == {"reason": "payer_out_of_allowance", "until": RESETS_AT.isoformat()}
        assert block["can_take_over"] is False
