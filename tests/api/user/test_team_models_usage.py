"""Which agents and workflows use a custom model, read before deleting it.

The delete confirm names them (they fall back to the default model), so the app reads the list first. Anyone
who may see the model may read it: every member for a team's model, only its owner for a person's own.
Anyone else is told the model doesn't exist, the same answer as the other model routes.
"""

from __future__ import annotations

import uuid

import pytest
from flask import Flask

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id
from tests.api.user.test_team_models import _public_dns, _registry  # noqa: F401  (autouse fixtures)
from tests.api.user.test_team_models import ROLES, _call, _db, _model, _pat, _team_model

ROUTE = ("/api/user/models/<string:model_id>/usage", "GET")


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; ana is an Admin, eddie an Editor, vi a Viewer. mallory is outside."""
    users = UsersRepository(pg_conn)
    for user in ROLES:
        users.upsert(user, email=f"{user}@x.io")
    tid = str(TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")["id"])
    members = TeamMembersRepository(pg_conn)
    for user, role in (("ana", "team_admin"), ("eddie", "team_editor"), ("vi", "team_viewer")):
        members.add_member(tid, user, role=role)
    return tid


def _usage(app, user, model_id, *, token=None, team_header=None):
    from docsgpt.api.user.models.routes import UserModelUsageResource

    return _call(app, UserModelUsageResource, "get", user, path=f"/api/user/models/{model_id}/usage",
                 args=[model_id], token=token, team=team_header)


class TestTeamModel:
    @pytest.mark.parametrize("user", ("alice", "ana", "eddie", "vi"))
    def test_every_member_reads_the_teams_agents_that_use_it(self, app, pg_conn, team, user):
        mid = str(_team_model(pg_conn, team)["id"])
        agent = AgentsRepository(pg_conn).create(principal_id(team), "Helper", "draft", default_model_id=mid)
        # Someone's own agent naming the team's model is not the team's usage.
        AgentsRepository(pg_conn).create("ana", "Mine", "draft", default_model_id=mid)
        with _db(pg_conn):
            resp = _usage(app, user, mid)

        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["success"] is True
        assert body["usage"] == {"agents": [{"id": str(agent["id"]), "name": "Helper"}], "workflows": []}

    def test_reading_it_deletes_nothing(self, app, pg_conn, team):
        from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository

        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn):
            _usage(app, "ana", mid)

        assert UserCustomModelsRepository(pg_conn).get_by_id(mid) is not None

    def test_an_outsider_is_told_it_doesnt_exist(self, app, pg_conn, team):
        mid = str(_team_model(pg_conn, team)["id"])
        AgentsRepository(pg_conn).create(principal_id(team), "Helper", "draft", default_model_id=mid)
        with _db(pg_conn):
            resp = _usage(app, "mallory", mid, team_header=team)

        assert resp.status_code == 404
        body = resp.get_json()
        assert body["error"] == "model_not_found" and "usage" not in body

    def test_a_token_with_models_read_reads_it(self, app, pg_conn, team):
        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn):
            resp = _usage(app, "vi", mid, token=_pat("vi", scopes=("models:read",)))

        assert resp.status_code == 200 and resp.get_json()["usage"] == {"agents": [], "workflows": []}


class TestPersonalModel:
    def test_the_owner_reads_their_agents_that_use_it(self, app, pg_conn, team):
        mid = str(_model(pg_conn, "eddie")["id"])
        agent = AgentsRepository(pg_conn).create("eddie", "Drafts", "draft", models=[mid])
        with _db(pg_conn):
            resp = _usage(app, "eddie", mid)

        assert resp.status_code == 200
        assert resp.get_json()["usage"]["agents"] == [{"id": str(agent["id"]), "name": "Drafts"}]

    @pytest.mark.parametrize("user", ("ana", "alice", None))
    def test_anyone_else_is_told_it_doesnt_exist(self, app, pg_conn, team, user):
        mid = str(_model(pg_conn, "eddie")["id"])
        AgentsRepository(pg_conn).create("eddie", "Drafts", "draft", default_model_id=mid)
        with _db(pg_conn):
            resp = _usage(app, user, mid, team_header=team)

        assert resp.status_code == (404 if user else 401)
        assert "usage" not in (resp.get_json() or {})

    def test_an_unknown_id_is_not_found(self, app, pg_conn, team):
        with _db(pg_conn):
            resp = _usage(app, "eddie", str(uuid.uuid4()))

        assert resp.status_code == 404 and resp.get_json()["error"] == "model_not_found"


class TestTokenRules:
    def test_the_route_is_a_models_read_kept_from_the_agent_tool(self):
        from docsgpt.api.pat.agent_tool import LEFT_OUT
        from docsgpt.api.pat.rules import RULES

        assert RULES[ROUTE].scopes == ("models:read",)
        assert any(ROUTE in routes for routes in LEFT_OUT.values())
