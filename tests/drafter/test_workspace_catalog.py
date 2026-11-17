"""The drafter's catalogue follows the workspace.

Personal never offers a team's items; a team offers the team's own and nothing personal, since a team agent may
reference only its team's items. An agent being edited decides the workspace by itself.
"""

from __future__ import annotations

import uuid

from flask import Flask

from docsgpt.drafter.catalog import read_workspace
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

OWNER, EDITOR, VIEWER, STRANGER = "cat-alice", "cat-eddie", "cat-vera", "cat-stan"


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", OWNER)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, OWNER, role="team_admin")
    repo.add_member(tid, EDITOR, role="team_editor")
    repo.add_member(tid, VIEWER, role="team_viewer")
    return tid, principal_id(tid)


def _items(conn, owner, tag):
    source = str(SourcesRepository(conn).create(f"{tag} source", user_id=owner, type="local")["id"])
    tool = str(UserToolsRepository(conn).create(
        owner, "api_tool", display_name=f"{tag} tool", description="", actions=[], status=True, config={},
    )["id"])
    prompt = str(PromptsRepository(conn).create(owner, f"{tag} prompt", "Be brief.")["id"])
    return source, tool, prompt


def _ids(ws, kind):
    return set(ws.attachable.get(kind, []))


class TestCatalogueByWorkspace:
    def test_personal_offers_no_team_items(self, pg_conn):
        tid, principal = _team(pg_conn)
        team_items = _items(pg_conn, principal, "team")
        own_items = _items(pg_conn, EDITOR, "own")
        ws = read_workspace(pg_conn, EDITOR)
        for kind, team_id, own_id in zip(("sources", "tools", "prompts"), team_items, own_items):
            assert own_id in _ids(ws, kind)
            assert team_id not in _ids(ws, kind)

    def test_a_forced_grant_brings_no_team_item_into_personal(self, pg_conn):
        tid, principal = _team(pg_conn)
        source, _tool, _prompt = _items(pg_conn, principal, "team")
        side = TeamsRepository(pg_conn).create("Side", f"side-{uuid.uuid4().hex[:6]}", OWNER)
        TeamMembersRepository(pg_conn).add_member(str(side["id"]), STRANGER)
        TeamResourceGrantsRepository(pg_conn).grant(str(side["id"]), "source", source, OWNER, OWNER)
        assert source not in _ids(read_workspace(pg_conn, STRANGER), "sources")

    def test_a_team_offers_its_own_items_and_nothing_personal(self, pg_conn):
        tid, principal = _team(pg_conn)
        team_items = _items(pg_conn, principal, "team")
        own_items = _items(pg_conn, VIEWER, "own")
        ws = read_workspace(pg_conn, VIEWER, owner_id=principal)
        for kind, team_id, own_id in zip(("sources", "tools", "prompts"), team_items, own_items):
            assert team_id in _ids(ws, kind)
            assert own_id not in _ids(ws, kind)
        # Team rows aren't "shared" in their own workspace.
        assert not any(row.get("shared") for row in ws.sources)

    def test_a_non_member_asking_for_a_team_gets_nothing_of_it(self, pg_conn):
        tid, principal = _team(pg_conn)
        source, _tool, _prompt = _items(pg_conn, principal, "team")
        ws = read_workspace(pg_conn, STRANGER, owner_id=principal)
        assert source not in _ids(ws, "sources")

    def test_the_agent_being_edited_decides_the_workspace(self, pg_conn):
        tid, principal = _team(pg_conn)
        source, _tool, _prompt = _items(pg_conn, principal, "team")
        own_source, _t, _p = _items(pg_conn, EDITOR, "own")
        agent = str(AgentsRepository(pg_conn).create(principal, "Bot", "draft")["id"])
        ws = read_workspace(pg_conn, EDITOR, agent)
        assert ws.agent and ws.agent["id"] == agent
        assert source in _ids(ws, "sources")
        assert own_source not in _ids(ws, "sources")

    def test_the_request_header_picks_the_team(self, pg_conn):
        tid, principal = _team(pg_conn)
        source, _tool, _prompt = _items(pg_conn, principal, "team")
        app = Flask(__name__)
        with app.test_request_context("/api/drafter", headers={WORKSPACE_HEADER: tid}):
            from flask import request

            request.decoded_token = {"sub": EDITOR}
            ws = read_workspace(pg_conn, EDITOR)
        assert source in _ids(ws, "sources")

    def test_the_requests_team_picks_it_after_the_request(self, pg_conn):
        tid, principal = _team(pg_conn)
        source, _tool, _prompt = _items(pg_conn, principal, "team")
        own_source, _t, _p = _items(pg_conn, EDITOR, "own")
        # No request context: the drafter reads on its stream's thread.
        ws = read_workspace(pg_conn, EDITOR, team_id=tid)
        assert source in _ids(ws, "sources")
        assert own_source not in _ids(ws, "sources")

    def test_a_non_member_naming_a_team_after_the_request_gets_nothing_of_it(self, pg_conn):
        tid, principal = _team(pg_conn)
        source, _tool, _prompt = _items(pg_conn, principal, "team")
        assert source not in _ids(read_workspace(pg_conn, STRANGER, team_id=tid), "sources")

    def test_the_agent_being_edited_still_decides_over_the_requests_team(self, pg_conn):
        tid, principal = _team(pg_conn)
        team_source, _tool, _prompt = _items(pg_conn, principal, "team")
        own_source, _t, _p = _items(pg_conn, EDITOR, "own")
        agent = str(AgentsRepository(pg_conn).create(EDITOR, "Mine", "draft")["id"])
        ws = read_workspace(pg_conn, EDITOR, agent, team_id=tid)
        assert own_source in _ids(ws, "sources")
        assert team_source not in _ids(ws, "sources")
