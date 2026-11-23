"""How many of a team's custom models each member added, on the members list its Owner and Admins read.

A team model's key stays in use when whoever added it leaves, so the remove-member dialog says how many they
added. Driven through the real app.py chokepoint against real Postgres; only ``handle_auth`` /
``resolve_roles`` are patched and the route module's sessions are pointed at the per-test ``pg_conn``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
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
        ):
            stack.enter_context(patch(target, _yield))
        yield pg_conn


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _team(conn, name="Operations"):
    users = UsersRepository(conn)
    for user in ("lena", "ana", "ed", "vi"):
        users.upsert(user, email=f"{user}@x.io")
    team = TeamsRepository(conn).create(name, f"ops-{uuid.uuid4().hex[:6]}", "lena")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "lena", role="team_admin")
    repo.add_member(tid, "ana", role="team_admin")
    repo.add_member(tid, "ed", role="team_editor")
    repo.add_member(tid, "vi", role="team_viewer")
    return tid


def _model(conn, owner, by=None, name="Mistral"):
    return UserCustomModelsRepository(conn).create(
        owner, "mistral-large", name, "https://api.mistral.ai/v1", "sk-test", created_by=by,
    )


def _members(client, tid, user):
    with _as(user):
        resp = client.get(f"/api/teams/{tid}/members")
    assert resp.status_code == 200, resp.data
    return {m["user_id"]: m for m in json.loads(resp.data)["members"]}


class TestCustomModelsAdded:
    def test_admins_see_how_many_team_models_each_member_added(self, client, db):
        tid = _team(db)
        _model(db, principal_id(tid), by="ana")
        _model(db, principal_id(tid), by="ana", name="Second")
        _model(db, principal_id(tid), by="ed", name="Ed's")
        members = _members(client, tid, "lena")
        assert members["ana"]["custom_models"] == 2
        assert members["ed"]["custom_models"] == 1
        assert members["vi"]["custom_models"] == 0

    def test_only_the_teams_own_models_count(self, client, db):
        tid = _team(db)
        other = _team(db, name="Elsewhere")
        _model(db, principal_id(other), by="ana")
        _model(db, "ana")
        assert _members(client, tid, "lena")["ana"]["custom_models"] == 0

    def test_a_viewer_does_not_see_the_count(self, client, db):
        tid = _team(db)
        _model(db, principal_id(tid), by="ana")
        members = _members(client, tid, "vi")
        assert all("custom_models" not in m for m in members.values())
