"""What a team's outside policy does to export and to its chats' share links.

* Export takes a team's agent outside: a locked team refuses it to everyone (403 ``team_locked``),
  and unlocking brings back today's rule (Editors and above).
* A team chat's share link counts as outside: making one follows the policy (Admins, or Editors too
  under ``editors``; nobody while locked, as ``team_locked``), and the team's existing links, with the
  artifacts they reach, answer 404 while the team is locked and come back when it unlocks.
* A Personal chat's link never depends on any team.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask, request
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.principal import principal_id

SHARING = "docsgpt.api.user.sharing.routes"
PORT = "docsgpt.api.user.agents.portability"


@pytest.fixture
def use_conn(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with patch(f"{SHARING}.db_readonly", _yield), patch(f"{SHARING}.db_session", _yield), patch(
        f"{PORT}.db_readonly", _yield
    ), patch(f"{PORT}.db_session", _yield):
        yield pg_conn


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    for user, role in (("adam", "team_admin"), ("eddie", "team_editor"), ("vera", "team_viewer")):
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _policy(conn, team_id, policy):
    conn.execute(
        text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id}
    )


def _chat(conn, user, team_id=None) -> str:
    repo = ConversationsRepository(conn)
    cid = str(repo.create(user, "Chat", team_id=team_id, visibility="listed")["id"])
    repo.append_message(cid, {"prompt": "q", "response": "a", "metadata": {}})
    return cid


def _call(resource_cls, method, *, path, user=None, json=None, query=None, **kwargs):
    with Flask(__name__).test_request_context(path, method=method.upper(), json=json, query_string=query or {}):
        request.decoded_token = {"sub": user} if user else None
        return getattr(resource_cls(), method)(**kwargs)


def _share(cid, user):
    from docsgpt.api.user.sharing.routes import ShareConversation

    return _call(ShareConversation, "post", path="/api/share", user=user, json={"conversation_id": cid},
                 query={"isPromptable": "false"})


def _read(identifier):
    from docsgpt.api.user.sharing.routes import GetPubliclySharedConversations

    return _call(GetPubliclySharedConversations, "get", path=f"/api/shared_conversation/{identifier}",
                 identifier=identifier)


def _export(user, agent_id):
    from docsgpt.api.user.agents.portability import ExportAgent

    return _call(ExportAgent, "get", path="/api/export_agent", user=user, query={"id": agent_id})


class TestExport:
    @pytest.mark.parametrize("user", ["alice", "adam", "eddie"])
    def test_a_locked_teams_agent_is_not_exported(self, use_conn, user):
        tid, principal = _team(use_conn)
        ag = str(AgentsRepository(use_conn).create(principal, "Team Bot", "draft", created_by="adam")["id"])
        _policy(use_conn, tid, "locked")
        response = _export(user, ag)
        assert response.status_code == 403
        assert response.get_json()["error"] == "team_locked"

    def test_unlocking_brings_export_back(self, use_conn):
        tid, principal = _team(use_conn)
        ag = str(AgentsRepository(use_conn).create(principal, "Team Bot", "draft", created_by="adam")["id"])
        _policy(use_conn, tid, "locked")
        _policy(use_conn, tid, "admins")
        assert _export("eddie", ag).status_code == 200

    def test_a_viewer_of_a_locked_team_gets_the_role_refusal(self, use_conn):
        tid, principal = _team(use_conn)
        ag = str(AgentsRepository(use_conn).create(principal, "Team Bot", "draft", created_by="adam")["id"])
        _policy(use_conn, tid, "locked")
        response = _export("vera", ag)
        assert response.status_code == 403
        assert response.get_json().get("error") != "team_locked"

    def test_a_personal_agent_exports_whatever_its_owners_teams_say(self, use_conn):
        tid, _ = _team(use_conn)
        _policy(use_conn, tid, "locked")
        ag = str(AgentsRepository(use_conn).create("eddie", "Mine", "draft")["id"])
        assert _export("eddie", ag).status_code == 200


class TestMakingATeamChatLink:
    def test_an_editor_may_under_editors(self, use_conn):
        tid, _ = _team(use_conn)
        _policy(use_conn, tid, "editors")
        assert _share(_chat(use_conn, "eddie", tid), "eddie").status_code == 201

    def test_an_editor_may_not_under_admins(self, use_conn):
        tid, _ = _team(use_conn)
        response = _share(_chat(use_conn, "eddie", tid), "eddie")
        assert response.status_code == 403
        assert response.get_json()["error"] == "workspace_role_required"

    def test_a_viewer_never_may(self, use_conn):
        tid, _ = _team(use_conn)
        _policy(use_conn, tid, "editors")
        response = _share(_chat(use_conn, "vera", tid), "vera")
        assert response.status_code == 403
        assert response.get_json()["error"] == "workspace_role_required"

    @pytest.mark.parametrize("user", ["alice", "adam"])
    def test_nobody_may_while_locked(self, use_conn, user):
        tid, _ = _team(use_conn)
        _policy(use_conn, tid, "locked")
        cid = _chat(use_conn, user, tid)
        response = _share(cid, user)
        assert response.status_code == 403
        assert response.get_json()["error"] == "team_locked"
        assert use_conn.execute(
            text("SELECT count(*) FROM shared_conversations WHERE conversation_id = CAST(:c AS uuid)"), {"c": cid}
        ).scalar() == 0


class TestReadingATeamChatLink:
    def _link(self, conn):
        tid, _ = _team(conn)
        cid = _chat(conn, "adam", tid)
        response = _share(cid, "adam")
        assert response.status_code == 201
        return tid, cid, response.get_json()["identifier"]

    def test_a_locked_teams_link_is_not_found_and_comes_back_on_unlock(self, use_conn):
        tid, _, identifier = self._link(use_conn)
        assert _read(identifier).status_code == 200
        _policy(use_conn, tid, "locked")
        assert _read(identifier).status_code == 404
        _policy(use_conn, tid, "admins")
        response = _read(identifier)
        assert response.status_code == 200
        assert response.get_json()["queries"][0]["response"] == "a"

    def test_its_artifacts_are_not_reached_while_locked(self, use_conn):
        from docsgpt.api.user.artifacts.authz import user_can_access_conversation

        tid, cid, identifier = self._link(use_conn)
        assert user_can_access_conversation(use_conn, cid, None, identifier) is True
        _policy(use_conn, tid, "locked")
        assert user_can_access_conversation(use_conn, cid, None, identifier) is False
        # A member reading their own chat isn't going outside.
        assert user_can_access_conversation(use_conn, cid, "adam", None) is True

    def test_a_personal_chats_link_is_unaffected(self, use_conn):
        tid, _ = _team(use_conn)
        _policy(use_conn, tid, "locked")
        cid = _chat(use_conn, "adam")
        response = _share(cid, "adam")
        assert response.status_code == 201
        assert _read(response.get_json()["identifier"]).status_code == 200


class TestAReceivingTeamsChatOnAnotherTeamsAgent:
    """Dev chats with Ops' agent shared into Dev: the link carries Ops' agent's answers outside, so Ops' lock
    pauses it too, and no new link is made meanwhile."""

    def _world(self, conn):
        from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository

        ops, ops_p = _team(conn)
        dev = str(TeamsRepository(conn).create("Dev", f"dev-{uuid.uuid4().hex[:6]}", "dora")["id"])
        TeamMembersRepository(conn).add_member(dev, "dora", role="team_admin")
        agent = str(AgentsRepository(conn).create(ops_p, "Ops helper", "published", created_by="alice")["id"])
        TeamItemSharesRepository(conn).share(ops, dev, "agent", agent, "adam")
        repo = ConversationsRepository(conn)
        cid = str(repo.create("dora", "Chat", team_id=dev, visibility="listed", agent_id=agent)["id"])
        repo.append_message(cid, {"prompt": "q", "response": "a", "metadata": {}})
        return ops, cid

    def test_the_owning_teams_lock_pauses_the_link_and_unlocking_brings_it_back(self, use_conn):
        from docsgpt.api.user.artifacts.authz import user_can_access_conversation

        ops, cid = self._world(use_conn)
        response = _share(cid, "dora")
        assert response.status_code == 201
        identifier = response.get_json()["identifier"]
        assert _read(identifier).status_code == 200
        _policy(use_conn, ops, "locked")
        assert _read(identifier).status_code == 404
        assert user_can_access_conversation(use_conn, cid, None, identifier) is False
        _policy(use_conn, ops, "admins")
        assert _read(identifier).status_code == 200
        assert user_can_access_conversation(use_conn, cid, None, identifier) is True

    def test_no_link_is_made_while_the_owning_team_is_locked(self, use_conn):
        ops, cid = self._world(use_conn)
        _policy(use_conn, ops, "locked")
        response = _share(cid, "dora")
        assert response.status_code == 403
        assert response.get_json()["error"] == "team_locked"
