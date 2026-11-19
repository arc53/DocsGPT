"""Who may start a run of someone else's agent, and when a deactivated owner pauses it.

Running another person's agent needs ownership, a team grant, the agent's
share link (its token presented, or the record that the caller opened the
link) or its API key. Knowing the agent's id is not enough. While the owner's
account is deactivated, the link and the key are refused; a team grant is not.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.owner_pause import AgentPausedError
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.users import UsersRepository


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "docsgpt.api.answer.services.stream_processor.db_readonly", _yield
    ), patch("docsgpt.api.answer.services.stream_processor.db_session", _yield):
        yield


def _processor(data=None, sub="stranger"):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    return StreamProcessor(dict(data or {}), {"sub": sub} if sub else None)


def _link_shared_agent(conn, owner="owner", **extra):
    return AgentsRepository(conn).create(
        owner, "a", "published", key="agent-key", shared=True, shared_token="link-token", **extra,
    )


def _deactivate(conn, user_id):
    UsersRepository(conn).upsert(user_id)
    conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": user_id})


def _grant_team_viewer(conn, agent_id, owner, member):
    import uuid

    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), "agent", agent_id, owner, owner, access_level="viewer",
    )


class TestLinkSharedAgentNeedsTheLink:
    def test_bare_id_of_a_link_shared_agent_is_refused(self, pg_conn):
        agent = _link_shared_agent(pg_conn)
        sp = _processor()
        with _patch_db(pg_conn), pytest.raises(Exception, match="Unauthorized"):
            sp._get_agent_key(str(agent["id"]), "stranger")

    def test_presenting_the_share_token_runs_it_as_a_link_user(self, pg_conn):
        agent = _link_shared_agent(pg_conn)
        sp = _processor({"shared_token": "link-token"})
        with _patch_db(pg_conn):
            key, shared, _ = sp._get_agent_key(str(agent["id"]), "stranger")
        assert key == "agent-key" and shared is True
        assert sp.public_link_usage is True

    def test_a_wrong_share_token_is_refused(self, pg_conn):
        agent = _link_shared_agent(pg_conn)
        sp = _processor({"shared_token": "guess"})
        with _patch_db(pg_conn), pytest.raises(Exception, match="Unauthorized"):
            sp._get_agent_key(str(agent["id"]), "stranger")

    def test_a_caller_who_opened_the_link_keeps_access(self, pg_conn):
        agent = _link_shared_agent(pg_conn)
        UsersRepository(pg_conn).upsert("stranger")
        UsersRepository(pg_conn).add_shared("stranger", str(agent["id"]))
        sp = _processor()
        with _patch_db(pg_conn):
            key, shared, _ = sp._get_agent_key(str(agent["id"]), "stranger")
        assert key == "agent-key" and shared is True

    def test_the_record_stops_counting_once_the_link_is_off(self, pg_conn):
        agent = _link_shared_agent(pg_conn)
        UsersRepository(pg_conn).upsert("stranger")
        UsersRepository(pg_conn).add_shared("stranger", str(agent["id"]))
        AgentsRepository(pg_conn).update(str(agent["id"]), "owner", {"shared": False})
        sp = _processor()
        with _patch_db(pg_conn), pytest.raises(Exception, match="Unauthorized"):
            sp._get_agent_key(str(agent["id"]), "stranger")

    def test_the_agents_api_key_with_its_id_runs_it(self, pg_conn):
        agent = AgentsRepository(pg_conn).create("owner", "a", "published", key="agent-key")
        sp = _processor({"api_key": "agent-key"}, sub=None)
        with _patch_db(pg_conn):
            key, _, _ = sp._get_agent_key(str(agent["id"]), None)
        assert key == "agent-key"

    def test_a_team_grant_still_runs_it(self, pg_conn):
        agent = AgentsRepository(pg_conn).create("owner", "a", "published", key="agent-key")
        _grant_team_viewer(pg_conn, str(agent["id"]), "owner", "member")
        sp = _processor(sub="member")
        with _patch_db(pg_conn):
            key, _, _ = sp._get_agent_key(str(agent["id"]), "member")
        assert key == "agent-key"
        assert sp.public_link_usage is False


class TestDeactivatedOwnerPausesOutsideAccess:
    def test_a_link_user_is_refused_while_the_owner_is_deactivated(self, pg_conn):
        agent = _link_shared_agent(pg_conn)
        _deactivate(pg_conn, "owner")
        sp = _processor({"shared_token": "link-token"})
        with _patch_db(pg_conn), pytest.raises(AgentPausedError) as err:
            sp._get_agent_key(str(agent["id"]), "stranger")
        # An outside caller is not told whose account it is.
        assert "owner" not in err.value.message.lower()

    def test_reactivating_the_owner_brings_the_link_back(self, pg_conn):
        agent = _link_shared_agent(pg_conn)
        _deactivate(pg_conn, "owner")
        pg_conn.execute(text("UPDATE users SET active = true WHERE user_id = 'owner'"))
        sp = _processor({"shared_token": "link-token"})
        with _patch_db(pg_conn):
            key, _, _ = sp._get_agent_key(str(agent["id"]), "stranger")
        assert key == "agent-key"

    def test_a_teammate_keeps_chatting_with_the_agent(self, pg_conn):
        agent = AgentsRepository(pg_conn).create("owner", "a", "published", key="agent-key")
        _grant_team_viewer(pg_conn, str(agent["id"]), "owner", "member")
        _deactivate(pg_conn, "owner")
        sp = _processor(sub="member")
        with _patch_db(pg_conn):
            key, _, _ = sp._get_agent_key(str(agent["id"]), "member")
        assert key == "agent-key"

    def test_the_api_key_is_refused_while_the_owner_is_deactivated(self, pg_conn):
        AgentsRepository(pg_conn).create("owner", "a", "published", key="agent-key")
        _deactivate(pg_conn, "owner")
        sp = _processor({"api_key": "agent-key", "question": "q"}, sub=None)
        with _patch_db(pg_conn), pytest.raises(AgentPausedError):
            sp._configure_agent()

    def test_the_api_key_works_while_the_owner_is_active(self, pg_conn):
        AgentsRepository(pg_conn).create("owner", "a", "published", key="agent-key")
        UsersRepository(pg_conn).upsert("owner")
        sp = _processor({"api_key": "agent-key", "question": "q"}, sub=None)
        with _patch_db(pg_conn):
            sp._configure_agent()
        assert sp.initial_user_id == "owner"
