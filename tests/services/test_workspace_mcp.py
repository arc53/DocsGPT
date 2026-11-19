"""The MCP ``search_docs`` tool on a team agent: the agent's key decides the workspace, never the request.

The MCP server authenticates with an agent API key, and a key works in its
agent's workspace whatever the request names: a team agent's key searches the
team's sources only, and stops when nobody pays for its outside traffic.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    monkeypatch.setattr("docsgpt.services.search_service.db_readonly", _yield)
    monkeypatch.setattr("docsgpt.mcp_server.origin_refusal", lambda *a, **k: None)
    return pg_conn


def _team(conn, owner="alice", name="Ops"):
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    TeamMembersRepository(conn).add_member(tid, owner, role="team_admin")
    TeamMembersRepository(conn).add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _source(conn, owner) -> str:
    created_by = "alice" if owner.startswith("__team__") else None
    row = SourcesRepository(conn).create("Docs", user_id=owner, created_by=created_by)
    return str(row["id"])


def _team_agent(conn, principal, sources, *, payer="alice"):
    key = f"k-{uuid.uuid4().hex[:8]}"
    AgentsRepository(conn).create(
        principal, "Team bot", "published", key=key, access_payer_id=payer, created_by="alice",
        extra_source_ids=sources,
    )
    return key


async def _search_docs(key, workspace=None):
    from docsgpt.mcp_server import search_docs

    headers = {"authorization": f"Bearer {key}"}
    if workspace is not None:
        headers[WORKSPACE_HEADER.lower()] = workspace
    searched = []

    def _fake_search(query, source_ids, chunks):
        searched.extend(source_ids)
        return []

    with patch("docsgpt.mcp_server.get_http_headers", return_value=headers), patch(
        "docsgpt.services.search_service._search_sources", side_effect=_fake_search
    ), patch("docsgpt.services.search_service.tracing"):
        await search_docs(query="hi")
    return searched


class TestTeamAgentKey:
    @pytest.mark.asyncio
    async def test_searches_the_teams_sources_and_drops_a_members_own(self, db):
        _tid, principal = _team(db)
        team_source = _source(db, principal)
        members_source = _source(db, "eddie")
        key = _team_agent(db, principal, [team_source, members_source])

        assert await _search_docs(key) == [team_source]

    @pytest.mark.asyncio
    async def test_a_workspace_the_request_names_changes_nothing(self, db):
        _tid, principal = _team(db)
        other_tid, other_principal = _team(db, owner="olga", name="Other")
        team_source = _source(db, principal)
        _source(db, other_principal)
        key = _team_agent(db, principal, [team_source])

        assert await _search_docs(key, workspace=other_tid) == [team_source]
        assert await _search_docs(key, workspace="personal") == [team_source]

    @pytest.mark.asyncio
    async def test_nobody_to_pay_refuses_before_searching(self, db):
        _tid, principal = _team(db)
        key = _team_agent(db, principal, [_source(db, principal)], payer=None)

        with pytest.raises(PermissionError):
            await _search_docs(key)
