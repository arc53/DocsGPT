"""A person's chat on someone else's agent resumes on its own while they can still use the agent.

A continuation carries on the chatter's run and bills the chatter (``continuation_payer``), so a teammate's chat on
a shared personal agent may wake up when a job finishes, as the owner's own chat does. It stops resuming the moment
the grant goes. A public-link chat stays poll-only: the publisher pays for link traffic, and a continuation would
bill the chatter instead.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from docsgpt.background.context import auto_resume_allowed
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository


def _agent(conn, owner="lena"):
    return str(AgentsRepository(conn).create(owner, "Desk", "published", agent_type="classic")["id"])


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
        chat = str(ConversationsRepository(pg_conn).create("dana", "c", agent_id=agent_id)["id"])

        assert auto_resume_allowed(pg_conn, chat, "dana") is True

    def test_stops_resuming_once_the_grant_is_revoked(self, pg_conn):
        agent_id = _agent(pg_conn)
        team_id = _share_with(pg_conn, agent_id, "dana")
        chat = str(ConversationsRepository(pg_conn).create("dana", "c", agent_id=agent_id)["id"])
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id)

        assert auto_resume_allowed(pg_conn, chat, "dana") is False

    def test_stops_resuming_once_they_leave_the_team_it_was_shared_with(self, pg_conn):
        agent_id = _agent(pg_conn)
        team_id = _share_with(pg_conn, agent_id, "dana")
        chat = str(ConversationsRepository(pg_conn).create("dana", "c", agent_id=agent_id)["id"])
        pg_conn.execute(
            text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = 'dana'"), {"t": team_id}
        )

        assert auto_resume_allowed(pg_conn, chat, "dana") is False

    def test_an_agent_nobody_shared_with_them_stays_poll_only(self, pg_conn):
        agent_id = _agent(pg_conn)
        chat = str(ConversationsRepository(pg_conn).create("dana", "c", agent_id=agent_id)["id"])

        assert auto_resume_allowed(pg_conn, chat, "dana") is False

    def test_a_public_link_chat_stays_poll_only(self, pg_conn):
        agent_id = _agent(pg_conn)
        # Shared with them too: the link chat is still the publisher's traffic.
        _share_with(pg_conn, agent_id, "dana")
        chat = str(
            ConversationsRepository(pg_conn).create("dana", "c", agent_id=agent_id, is_shared_usage=True)["id"]
        )

        assert auto_resume_allowed(pg_conn, chat, "dana") is False

    def test_key_traffic_stays_poll_only(self, pg_conn):
        agent_id = _agent(pg_conn)
        _share_with(pg_conn, agent_id, "dana")
        chat = str(ConversationsRepository(pg_conn).create("dana", "c", agent_id=agent_id, api_key="k")["id"])

        assert auto_resume_allowed(pg_conn, chat, "dana") is False
