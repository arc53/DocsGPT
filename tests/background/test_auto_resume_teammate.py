"""A person's in-app chat on a published agent resumes on its own while they can still use the agent.

A continuation carries on the chatter's run and bills the chatter (``continuation_payer``), so the owner's own chat,
a teammate's chat on a shared personal agent and a member's chat on a team agent may wake up when a job finishes.
Rows are written as the chat writes them: an in-app chat on a published agent stores the agent's key, and every
non-owner's chat is saved as shared usage. A chat stops resuming the moment the grant goes. API-key, widget and
public-link traffic stays poll-only: the link is all such a caller holds, and the turn (not the row) says it is that
traffic.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from types import SimpleNamespace

from docsgpt.background.context import auto_resume_allowed, bind_turn
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository


KEY = "agent-key"


def _agent(conn, owner="lena"):
    return str(AgentsRepository(conn).create(owner, "Desk", "published", agent_type="classic", key=KEY)["id"])


def _chat(conn, user, agent_id, **kw):
    """A conversation as an in-app chat on a published agent saves it: with the agent's key."""
    kw.setdefault("is_shared_usage", user != "lena")
    return str(ConversationsRepository(conn).create(user, "c", agent_id=agent_id, api_key=KEY, **kw)["id"])


def _share_with(conn, agent_id, member, owner="lena"):
    """Share ``agent_id`` with a team holding ``member``; returns the team id."""
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    team_id = str(team["id"])
    TeamMembersRepository(conn).add_member(team_id, member)
    TeamResourceGrantsRepository(conn).grant(team_id, "agent", agent_id, owner, owner)
    return team_id


class TestATeammatesChat:
    def test_resumes_while_the_agent_is_shared_with_them(self, pg_conn):
        agent_id = _agent(pg_conn)
        _share_with(pg_conn, agent_id, "dana")

        assert auto_resume_allowed(pg_conn, _chat(pg_conn, "dana", agent_id), "dana") is True

    def test_stops_resuming_once_the_grant_is_revoked(self, pg_conn):
        agent_id = _agent(pg_conn)
        team_id = _share_with(pg_conn, agent_id, "dana")
        chat = _chat(pg_conn, "dana", agent_id)
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id)

        assert auto_resume_allowed(pg_conn, chat, "dana") is False

    def test_stops_resuming_once_they_leave_the_team_it_was_shared_with(self, pg_conn):
        agent_id = _agent(pg_conn)
        team_id = _share_with(pg_conn, agent_id, "dana")
        chat = _chat(pg_conn, "dana", agent_id)
        pg_conn.execute(
            text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = 'dana'"), {"t": team_id}
        )

        assert auto_resume_allowed(pg_conn, chat, "dana") is False

    def test_an_agent_nobody_shared_with_them_stays_poll_only(self, pg_conn):
        # A public-link chat: the link is all they have.
        agent_id = _agent(pg_conn)

        assert auto_resume_allowed(pg_conn, _chat(pg_conn, "dana", agent_id), "dana") is False


class TestAMembersChatOnATeamAgent:
    def test_resumes_while_they_stay_in_the_team(self, pg_conn):
        from docsgpt.workspaces.principal import principal_id

        team = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "lena")
        team_id = str(team["id"])
        TeamMembersRepository(pg_conn).add_member(team_id, "dana")
        chat = _chat(pg_conn, "dana", _agent(pg_conn, principal_id(team_id)), team_id=team_id)

        assert auto_resume_allowed(pg_conn, chat, "dana") is True
        TeamMembersRepository(pg_conn).remove_member(team_id, "dana")
        assert auto_resume_allowed(pg_conn, chat, "dana") is False


class TestTheOwnersChat:
    def test_the_owners_own_chat_on_their_published_agent_resumes(self, pg_conn):
        agent_id = _agent(pg_conn)

        assert auto_resume_allowed(pg_conn, _chat(pg_conn, "lena", agent_id), "lena") is True

    def test_a_key_chat_whose_agent_is_gone_stays_poll_only(self, pg_conn):
        chat = str(ConversationsRepository(pg_conn).create("lena", "c", api_key="old-key")["id"])

        assert auto_resume_allowed(pg_conn, chat, "lena") is False


class TestOutsideTraffic:
    def _executor(self, **kw):
        return SimpleNamespace(headless=False, workflow_run_id=None, background=None, **kw)

    def _bound(self, executor, chat, user):
        return bind_turn(executor, conversation_id=chat, message_id="m", decoded_token={"sub": user})

    def test_an_in_app_turn_resumes(self, pg_conn, monkeypatch):
        agent_id = _agent(pg_conn)
        chat = _chat(pg_conn, "lena", agent_id)
        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", lambda: _Same(pg_conn))
        context = self._bound(self._executor(external_caller=False, public_link_caller=False), chat, "lena")

        assert context.outside_caller is False
        assert context.auto_resume() is True

    def test_key_and_widget_traffic_stays_poll_only(self, pg_conn, monkeypatch):
        # Saved like the owner's own chat (their id, the agent's key): only the turn tells them apart.
        agent_id = _agent(pg_conn)
        chat = _chat(pg_conn, "lena", agent_id)
        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", lambda: _Same(pg_conn))
        context = self._bound(self._executor(external_caller=True, public_link_caller=False), chat, "lena")

        assert context.outside_caller is True
        assert context.auto_resume() is False

    def test_a_public_link_turn_stays_poll_only(self, pg_conn, monkeypatch):
        # Shared with them too: what the turn was decides, not a grant they also hold.
        agent_id = _agent(pg_conn)
        _share_with(pg_conn, agent_id, "dana")
        chat = _chat(pg_conn, "dana", agent_id)
        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", lambda: _Same(pg_conn))
        context = self._bound(self._executor(external_caller=False, public_link_caller=True), chat, "dana")

        assert context.auto_resume() is False

    def test_a_team_agents_key_traffic_stays_poll_only(self, pg_conn):
        from docsgpt.workspaces.principal import principal_id

        team = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "lena")
        principal = principal_id(str(team["id"]))
        agent_id = _agent(pg_conn, principal)
        chat = _chat(pg_conn, principal, agent_id, is_shared_usage=False)

        assert auto_resume_allowed(pg_conn, chat, principal) is False


class _Same:
    """``db_readonly()`` handing back the test's connection."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False
