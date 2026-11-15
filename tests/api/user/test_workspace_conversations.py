"""Conversations by workspace.

Lists and search show one workspace's chats: the header picks it, Personal shows
chats with no team. A team chat is readable only while its owner is still in the
team; it comes back if they are re-added. A team chat's share link is a
read-only snapshot an Admin makes.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from flask import Flask, request

from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def use_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    for module in ("docsgpt.api.user.conversations.routes", "docsgpt.api.user.sharing.routes"):
        monkeypatch.setattr(f"{module}.db_readonly", _yield)
        monkeypatch.setattr(f"{module}.db_session", _yield)
    return pg_conn


def _team(conn, owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"), ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _chat(conn, user, team_id=None, name="Chat") -> str:
    repo = ConversationsRepository(conn)
    cid = str(repo.create(user, name, team_id=team_id, visibility="listed")["id"])
    repo.append_message(cid, {"prompt": f"about {name}", "response": "ok", "metadata": {}})
    return cid


def _call(resource_cls, method="get", *, path="/api/x", user="vera", workspace=None, json=None, query=None):
    headers = {WORKSPACE_HEADER: workspace} if workspace is not None else {}
    with Flask(__name__).test_request_context(
        path, method=method.upper(), headers=headers, json=json, query_string=query or {}
    ):
        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)()


def _list(user="vera", workspace=None):
    from docsgpt.api.user.conversations.routes import GetConversations

    return _call(GetConversations, path="/api/get_conversations", user=user, workspace=workspace)


def _single(cid, user="vera"):
    from docsgpt.api.user.conversations.routes import GetSingleConversation

    return _call(GetSingleConversation, path="/api/get_single_conversation", user=user, query={"id": cid})


def _search(q, user="vera", workspace=None):
    from docsgpt.api.user.conversations.routes import SearchConversations

    return _call(SearchConversations, path="/api/search_conversations", user=user, workspace=workspace, query={"q": q})


class TestListsArePerWorkspace:
    def test_personal_and_team_lists_split(self, use_conn):
        tid, _ = _team(use_conn)
        mine = _chat(use_conn, "vera", name="Mine")
        ours = _chat(use_conn, "vera", tid, name="Ours")

        personal = _list().get_json()
        assert [c["id"] for c in personal] == [mine]
        assert personal[0]["workspace"] == {"kind": "personal", "team_id": None}

        team = _list(workspace=tid).get_json()
        assert [c["id"] for c in team] == [ours]
        assert team[0]["workspace"] == {"kind": "team", "team_id": tid}

    def test_another_persons_team_chats_never_list(self, use_conn):
        tid, _ = _team(use_conn)
        _chat(use_conn, "eddie", tid)
        assert _list(workspace=tid).get_json() == []

    def test_a_team_the_caller_is_not_in_is_not_found(self, use_conn):
        tid, _ = _team(use_conn)
        _chat(use_conn, "vera", tid)
        response = _list(user="eve", workspace=tid)
        assert response.status_code == 404
        assert response.get_json()["error"] == "workspace_not_found"
        assert _search("about", user="eve", workspace=tid).status_code == 404

    def test_search_is_per_workspace(self, use_conn):
        tid, _ = _team(use_conn)
        mine = _chat(use_conn, "vera", name="Mine")
        ours = _chat(use_conn, "vera", tid, name="Ours")
        assert [c["id"] for c in _search("about").get_json()] == [mine]
        found = _search("about", workspace=tid).get_json()
        assert [c["id"] for c in found] == [ours]
        assert found[0]["workspace"]["team_id"] == tid

    def test_the_single_chat_names_its_workspace(self, use_conn):
        tid, _ = _team(use_conn)
        cid = _chat(use_conn, "vera", tid)
        body = _single(cid).get_json()
        assert body["workspace"] == {"kind": "team", "team_id": tid}


class TestExMember:
    def test_an_ex_member_loses_their_team_chats_and_gets_them_back(self, use_conn):
        from docsgpt.api.user.conversations.routes import GetMessageTail, UpdateConversationName

        tid, _ = _team(use_conn)
        cid = _chat(use_conn, "vera", tid, name="Ours")
        message_id = str(ConversationsRepository(use_conn).get_messages(cid)[0]["id"])

        TeamMembersRepository(use_conn).remove_member(tid, "vera")

        assert _single(cid).status_code == 404
        assert _list(workspace=tid).status_code == 404
        assert _list().get_json() == []
        assert _search("about").get_json() == []
        with Flask(__name__).test_request_context(f"/api/messages/{message_id}/tail"):
            request.decoded_token = {"sub": "vera"}
            assert GetMessageTail().get(message_id).status_code == 404
        _call(UpdateConversationName, "post", json={"id": cid, "name": "Renamed"})
        assert ConversationsRepository(use_conn).team_id_of(cid) == tid
        name = use_conn.exec_driver_sql(f"SELECT name FROM conversations WHERE id = '{cid}'").scalar()
        assert name == "Ours"

        TeamMembersRepository(use_conn).add_member(tid, "vera")
        assert _single(cid).status_code == 200
        assert [c["id"] for c in _list(workspace=tid).get_json()] == [cid]

    def test_the_reconnect_reader_checks_membership(self, use_conn, monkeypatch):
        from docsgpt.api import async_sse

        @contextmanager
        def _yield():
            yield use_conn

        monkeypatch.setattr(async_sse, "db_readonly", _yield)
        tid, _ = _team(use_conn)
        cid = _chat(use_conn, "vera", tid)
        repo = ConversationsRepository(use_conn)
        message = repo.reserve_message(cid, prompt="q", placeholder_response="...", request_id="r1", status="pending")
        mid = str(message["id"])
        assert async_sse._user_owns_message(mid, message["user_id"]) is True
        TeamMembersRepository(use_conn).remove_member(tid, "vera")
        assert async_sse._user_owns_message(mid, "vera") is False


class TestTeamChatShareLinks:
    def _share(self, cid, user, promptable=False):
        from docsgpt.api.user.sharing.routes import ShareConversation

        return _call(
            ShareConversation, "post", path="/api/share", user=user,
            json={"conversation_id": cid}, query={"isPromptable": "true" if promptable else "false"},
        )

    def test_an_editor_cannot_share_their_team_chat(self, use_conn):
        tid, _ = _team(use_conn)
        cid = _chat(use_conn, "eddie", tid)
        response = self._share(cid, "eddie")
        assert response.status_code == 403
        assert response.get_json()["error"] == "workspace_role_required"

    def test_an_admin_shares_a_read_only_snapshot(self, use_conn):
        tid, _ = _team(use_conn)
        cid = _chat(use_conn, "adam", tid)
        assert self._share(cid, "adam").status_code == 201

    def test_no_one_makes_a_promptable_link_on_a_team_chat(self, use_conn):
        tid, _ = _team(use_conn)
        cid = _chat(use_conn, "adam", tid)
        response = self._share(cid, "adam", promptable=True)
        assert response.status_code == 403
        assert response.get_json()["error"] == "promptable_share_personal_only"

    def test_a_personal_chat_still_shares(self, use_conn):
        _team(use_conn)
        cid = _chat(use_conn, "eddie")
        assert self._share(cid, "eddie").status_code == 201
