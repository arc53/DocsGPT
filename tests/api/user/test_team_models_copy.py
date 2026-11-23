"""Copy to a team: a person brings their own custom model into a team they administer without retyping the key.

The copy is a new row the team's principal owns, its key re-sealed for the principal, recording the person as
the one who added it; the person's own row is left exactly as it was. Only the model's owner may copy it, only
into a team where they are an Admin or the Owner, never twice into the same team, and never with a token.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from flask import Flask

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.security.encryption import decrypt_tool_credentials
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id
from tests.api.user.test_team_models import _public_dns, _registry  # noqa: F401  (autouse fixtures)
from tests.api.user.test_team_models import ROLES, _audit, _call, _db, _model, _pat, _row, _team_model

ROUTES = "docsgpt.api.user.models.routes"


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


def _copy(app, user, model_id, body, *, token=None, team_header=None):
    from docsgpt.api.user.models.routes import UserModelCopyResource

    return _call(app, UserModelCopyResource, "post", user, path=f"/api/user/models/{model_id}/copy", body=body,
                 args=[model_id], token=token, team=team_header)


def _team_rows(conn, team):
    return UserCustomModelsRepository(conn).list_for_user(principal_id(team))


class TestCopy:
    @pytest.mark.parametrize("user", ("ana", "alice"))
    def test_an_admin_copies_their_model_into_the_team(self, app, pg_conn, team, user):
        mine = _model(pg_conn, user, name="My Llama", key="sk-mine")
        mid = str(mine["id"])
        before = _row(pg_conn, mid)
        principal = principal_id(team)
        with _db(pg_conn), patch(f"{ROUTES}.ModelRegistry.invalidate_user") as invalidate:
            resp = _copy(app, user, mid, {"team_id": team})

        assert resp.status_code == 201, resp.get_json()
        body = resp.get_json()
        assert body["id"] != mid
        assert (body["owner"], body["team_id"], body["source"]) == ("team", team, "team")
        assert body["created_by"]["user_id"] == user
        assert body["display_name"] == "My Llama" and body["upstream_model_id"] == "llama-3"
        row = _row(pg_conn, body["id"])
        assert row["user_id"] == principal and row["created_by"] == user
        # The key is the team's now: it opens with the principal, not with the person.
        assert decrypt_tool_credentials(row["api_key_encrypted"], principal)["api_key"] == "sk-mine"
        assert not decrypt_tool_credentials(row["api_key_encrypted"], user)
        # The person's own row is untouched.
        assert _row(pg_conn, mid) == before
        invalidate.assert_called_once_with(principal)

    def test_copying_is_audited(self, app, pg_conn, team):
        mine = _model(pg_conn, "ana", name="My Llama")
        with _db(pg_conn), patch(f"{ROUTES}.ModelRegistry.invalidate_user"):
            resp = _copy(app, "ana", str(mine["id"]), {"team_id": team})

        [meta] = _audit(pg_conn, "team.model_added")
        assert meta == {
            "team_id": team, "model_id": resp.get_json()["id"], "display_name": "My Llama",
            "upstream_model_id": "llama-3", "copied": True,
        }

    @pytest.mark.parametrize("user,status,code", [
        ("eddie", 403, "workspace_role_required"),
        ("vi", 403, "workspace_role_required"),
        ("mallory", 404, "workspace_not_found"),
    ])
    def test_below_admin_nothing_is_copied(self, app, pg_conn, team, user, status, code):
        mine = _model(pg_conn, user)
        with _db(pg_conn):
            resp = _copy(app, user, str(mine["id"]), {"team_id": team})

        assert resp.status_code == status and resp.get_json()["error"] == code
        assert _team_rows(pg_conn, team) == []
        assert _audit(pg_conn, "team.model_added") == []

    def test_an_unknown_team_is_not_found(self, app, pg_conn, team):
        mine = _model(pg_conn, "ana")
        with _db(pg_conn):
            for bad in ("not-a-team", "00000000-0000-0000-0000-000000000000"):
                resp = _copy(app, "ana", str(mine["id"]), {"team_id": bad})
                assert resp.status_code == 404 and resp.get_json()["error"] == "workspace_not_found"

    def test_the_team_is_required(self, app, pg_conn, team):
        mine = _model(pg_conn, "ana")
        with _db(pg_conn):
            resp = _copy(app, "ana", str(mine["id"]), {}, team_header=team)

        assert resp.status_code == 400 and resp.get_json()["error"] == "team_id_required"
        assert _team_rows(pg_conn, team) == []

    def test_someone_elses_model_is_not_found(self, app, pg_conn, team):
        theirs = _model(pg_conn, "eddie")
        with _db(pg_conn):
            resp = _copy(app, "ana", str(theirs["id"]), {"team_id": team})

        assert resp.status_code == 404 and resp.get_json()["error"] == "model_not_found"
        assert _team_rows(pg_conn, team) == []

    def test_a_teams_model_is_not_copied(self, app, pg_conn, team):
        theirs = _team_model(pg_conn, team)
        with _db(pg_conn):
            resp = _copy(app, "ana", str(theirs["id"]), {"team_id": team})

        assert resp.status_code == 404 and resp.get_json()["error"] == "model_not_found"
        assert len(_team_rows(pg_conn, team)) == 1

    def test_the_same_model_twice_is_refused(self, app, pg_conn, team):
        existing = _team_model(pg_conn, team, name="Already here")
        mine = UserCustomModelsRepository(pg_conn).create(
            "ana", "llama-3", "My Llama", "https://LLM.example.com/v1/", "sk-mine",
        )
        with _db(pg_conn):
            resp = _copy(app, "ana", str(mine["id"]), {"team_id": team})

        assert resp.status_code == 409
        assert resp.get_json()["error"] == "model_already_in_team"
        assert resp.get_json()["model_id"] == str(existing["id"])
        assert len(_team_rows(pg_conn, team)) == 1

    def test_a_token_cant_copy(self, app, pg_conn, team):
        mine = _model(pg_conn, "ana")
        with _db(pg_conn):
            resp = _copy(app, "ana", str(mine["id"]), {"team_id": team}, token=_pat("ana"))

        assert resp.status_code == 403 and resp.get_json()["error"] == "not_available_to_tokens"
        assert _team_rows(pg_conn, team) == []


class TestTokenRules:
    def test_the_route_is_a_models_write_tokens_are_refused(self):
        from docsgpt.api.pat.agent_tool import LEFT_OUT
        from docsgpt.api.pat.rules import RULES

        route = ("/api/user/models/<string:model_id>/copy", "POST")
        assert RULES[route].scopes == ("models:write",)
        assert any(route in routes for routes in LEFT_OUT.values())
