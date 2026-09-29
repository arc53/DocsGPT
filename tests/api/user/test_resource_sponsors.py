"""Resource sponsors: an editor's own tool/prompt/source runs inside the owner's agent.

An agent runs as its owner, so a resource the owner can't use used to be
dropped at run time even though an editor attached it. The editor who
attaches it becomes its sponsor (``resource_sponsors``); the resource then
runs while the sponsor can still edit the agent and still use the resource.
Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.api.user.resource_access import (
    active_sponsor,
    agent_refs,
    ref_principal,
    set_settings,
    sponsor_key,
    sponsors_after_save,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

OWNER, EDITOR, VIEWER, OTHER = "sp-owner", "sp-editor", "sp-viewer", "sp-other"

_DB_MODULES = (
    "docsgpt.api.user.agents.routes",
    "docsgpt.api.user.workflows.routes",
    "docsgpt.api.user.base",
    "docsgpt.agents.tool_executor",
    "docsgpt.api.answer.services.stream_processor",
    "docsgpt.agents.workflows.workflow_engine",
    "docsgpt.storage.db.session",
)


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    import importlib

    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for mod_name in _DB_MODULES:
            mod = importlib.import_module(mod_name)
            for attr in ("db_session", "db_readonly"):
                if hasattr(mod, attr):
                    stack.enter_context(patch(f"{mod_name}.{attr}", _yield))
        yield


def _call(app, conn, resource_cls, method, path, user, *, json=None, args=()):
    kwargs = {"method": method.upper()}
    if json is not None:
        kwargs["json"] = json
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method.lower())(*args)


def _status(resp) -> int:
    return resp[1] if isinstance(resp, tuple) else resp.status_code


def _share_agent(conn, agent_id):
    """Share the agent with a team: EDITOR as editor, VIEWER as viewer."""
    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", OWNER)
    tid = str(team["id"])
    for member, level in ((EDITOR, "editor"), (VIEWER, "viewer")):
        TeamMembersRepository(conn).add_member(tid, member)
        TeamResourceGrantsRepository(conn).grant(
            tid, "agent", agent_id, OWNER, OWNER, access_level=level, target_user_id=member
        )
    return tid


def _agent(conn, **extra):
    extra.setdefault("agent_type", "classic")
    extra.setdefault("chunks", 6)
    row = AgentsRepository(conn).create(
        OWNER, "Shared", "published", description="d", key=f"k-{uuid.uuid4().hex}", **extra
    )
    agent_id = str(row["id"])
    team_id = _share_agent(conn, agent_id)
    return agent_id, team_id


def _row(conn, agent_id):
    return AgentsRepository(conn).get_by_id(agent_id)


def _editor_resources(conn):
    tool = str(UserToolsRepository(conn).create(EDITOR, "api_tool")["id"])
    prompt = str(PromptsRepository(conn).create(EDITOR, "mine", "Editor prompt")["id"])
    source = str(SourcesRepository(conn).create("editor-src", user_id=EDITOR)["id"])
    return tool, prompt, source


def _put(app, conn, agent_id, user, body):
    from docsgpt.api.user.agents.routes import UpdateAgent

    return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", user,
                 json=body, args=(agent_id,))


# ---------------------------------------------------------------------------
# sponsors_after_save
# ---------------------------------------------------------------------------


class TestSponsorsAfterSave:
    def test_owner_usable_refs_need_no_sponsor(self, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        out = sponsors_after_save(pg_conn, "agent", _row(pg_conn, agent_id), OWNER, EDITOR, [("tool", tool)])
        assert out == {}

    def test_editor_resources_are_sponsored_by_editor(self, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, prompt, source = _editor_resources(pg_conn)
        refs = [("tool", tool), ("prompt", prompt), ("source", source)]
        out = sponsors_after_save(pg_conn, "agent", _row(pg_conn, agent_id), OWNER, EDITOR, refs)
        assert out == {sponsor_key(t, i): EDITOR for t, i in refs}

    def test_builtin_tool_and_preset_ids_are_skipped(self, pg_conn):
        from docsgpt.agents.default_tools import loaded_builtin_agent_tools, synthesize_builtin_agent_tool

        agent_id, _ = _agent(pg_conn)
        builtin = next(iter(loaded_builtin_agent_tools()), None)
        refs = [("prompt", "default")]
        if builtin:
            refs.append(("tool", str(synthesize_builtin_agent_tool(builtin)["id"])))
        assert sponsors_after_save(pg_conn, "agent", _row(pg_conn, agent_id), OWNER, EDITOR, refs) == {}

    def test_owner_save_keeps_editor_sponsor(self, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"tools": [tool], "resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        out = sponsors_after_save(pg_conn, "agent", _row(pg_conn, agent_id), OWNER, OWNER, [("tool", tool)])
        assert out == {sponsor_key("tool", tool): EDITOR}

    def test_removed_ref_drops_out(self, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"tools": [tool], "resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        assert sponsors_after_save(pg_conn, "agent", _row(pg_conn, agent_id), OWNER, EDITOR, []) == {}

    def test_another_editor_takes_over_when_sponsor_lost_access(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        # A tool shared with the whole team: both editors may use it in their agents.
        tool = str(UserToolsRepository(pg_conn).create(OTHER, "api_tool")["id"])
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER)
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "agent", agent_id, OWNER, OWNER, access_level="editor", target_user_id=OTHER
        )
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"tools": [tool], "resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)

        out = sponsors_after_save(pg_conn, "agent", _row(pg_conn, agent_id), OWNER, OTHER, [("tool", tool)])
        assert out == {sponsor_key("tool", tool): OTHER}

    def test_dead_sponsor_record_kept_when_nobody_qualifies(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"tools": [tool], "resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        out = sponsors_after_save(pg_conn, "agent", _row(pg_conn, agent_id), OWNER, OWNER, [("tool", tool)])
        assert out == {sponsor_key("tool", tool): EDITOR}


# ---------------------------------------------------------------------------
# active_sponsor / ref_principal (live checks)
# ---------------------------------------------------------------------------


class TestActiveSponsor:
    def _sponsored(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"tools": [tool], "resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        return agent_id, team_id, tool

    def test_live_sponsor_is_principal(self, pg_conn):
        agent_id, _, tool = self._sponsored(pg_conn)
        agent = _row(pg_conn, agent_id)
        assert active_sponsor(pg_conn, "agent", agent, "tool", tool) == EDITOR
        assert ref_principal(pg_conn, "agent", agent, "tool", tool) == EDITOR

    def test_owner_wins_over_sponsor(self, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        assert ref_principal(pg_conn, "agent", _row(pg_conn, agent_id), "tool", tool) == OWNER

    def test_sponsor_removed_from_agent_stops(self, pg_conn):
        agent_id, team_id, tool = self._sponsored(pg_conn)
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        assert active_sponsor(pg_conn, "agent", _row(pg_conn, agent_id), "tool", tool) is None

    def test_sponsor_demoted_to_viewer_stops(self, pg_conn):
        agent_id, team_id, tool = self._sponsored(pg_conn)
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "agent", agent_id, OWNER, OWNER, access_level="viewer", target_user_id=EDITOR
        )
        assert active_sponsor(pg_conn, "agent", _row(pg_conn, agent_id), "tool", tool) is None

    def test_sponsor_losing_the_resource_stops(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OTHER, "api_tool")["id"])
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "tool", tool, OTHER, OTHER, target_user_id=EDITOR
        )
        AgentsRepository(pg_conn).update_by_id(
            agent_id, {"resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        assert active_sponsor(pg_conn, "agent", _row(pg_conn, agent_id), "tool", tool) == EDITOR
        set_settings(pg_conn, "tool", tool, {"viewers_can_use_in_agents": False}, OTHER)
        assert active_sponsor(pg_conn, "agent", _row(pg_conn, agent_id), "tool", tool) is None

    def test_no_record_no_sponsor(self, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert ref_principal(pg_conn, "agent", _row(pg_conn, agent_id), "tool", tool) is None


# ---------------------------------------------------------------------------
# update_agent / get_agent
# ---------------------------------------------------------------------------


class TestAgentRoutes:
    def test_editor_attaching_own_resources_records_sponsor(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, prompt, source = _editor_resources(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR,
                    {"tools": [tool], "prompt_id": prompt, "source": source})
        assert _status(resp) == 200
        row = _row(pg_conn, agent_id)
        assert row["resource_sponsors"] == {
            sponsor_key("tool", tool): EDITOR,
            sponsor_key("prompt", prompt): EDITOR,
            sponsor_key("source", source): EDITOR,
        }
        assert set(agent_refs(row)) >= {("tool", tool), ("prompt", prompt), ("source", source)}

    def test_owner_save_does_not_wipe_sponsors(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR, {"tools": [tool]})) == 200
        assert _status(_put(app, pg_conn, agent_id, OWNER, {"name": "Renamed", "tools": [tool]})) == 200
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {sponsor_key("tool", tool): EDITOR}

    def test_detaching_clears_sponsor(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR, {"tools": [tool]})) == 200
        assert _status(_put(app, pg_conn, agent_id, EDITOR, {"tools": []})) == 200
        assert _row(pg_conn, agent_id)["resource_sponsors"] == {}

    def test_get_agent_lists_sponsors_for_editors_only(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgent
        from docsgpt.storage.db.repositories.users import UsersRepository

        agent_id, team_id = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        UsersRepository(pg_conn).upsert(EDITOR, email="bob@example.com")
        assert _status(_put(app, pg_conn, agent_id, EDITOR, {"tools": [tool]})) == 200

        path = f"/api/get_agent?id={agent_id}"
        owner_view = _call(app, pg_conn, GetAgent, "get", path, OWNER).get_json()
        assert owner_view["resource_sponsors"] == [
            {"type": "tool", "id": tool, "user_id": EDITOR, "label": "bob@example.com", "active": True}
        ]
        viewer_view = _call(app, pg_conn, GetAgent, "get", path, VIEWER).get_json()
        assert viewer_view["resource_sponsors"] == []

        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        owner_view = _call(app, pg_conn, GetAgent, "get", path, OWNER).get_json()
        assert owner_view["resource_sponsors"][0]["active"] is False


# ---------------------------------------------------------------------------
# run time
# ---------------------------------------------------------------------------


class TestRunTime:
    def _sponsored_agent(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool, prompt, source = _editor_resources(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR,
                    {"tools": [tool], "prompt_id": prompt, "source": source})
        assert _status(resp) == 200
        return _row(pg_conn, agent_id), team_id, tool, prompt, source

    def test_agent_key_toolset_includes_sponsored_tool(self, app, pg_conn):
        from docsgpt.agents.tool_executor import ToolExecutor

        agent, team_id, tool, _, _ = self._sponsored_agent(app, pg_conn)
        with _patch_db(pg_conn):
            tools = ToolExecutor(user_api_key=agent["key"], user=OWNER)._get_tools_by_api_key(agent["key"])
        assert tool in tools
        # The row is the tool owner's, so its credentials decrypt as the editor.
        assert tools[tool]["user_id"] == EDITOR

        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", str(agent["id"]), target_user_id=EDITOR)
        with _patch_db(pg_conn):
            tools = ToolExecutor(user_api_key=agent["key"], user=OWNER)._get_tools_by_api_key(agent["key"])
        assert tool not in tools

    def test_sponsored_prompt_renders(self, app, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_prompt_id

        agent, team_id, _, prompt, _ = self._sponsored_agent(app, pg_conn)
        with _patch_db(pg_conn):
            assert authorized_prompt_id(prompt, OWNER, agent) == prompt
            assert authorized_prompt_id(prompt, OWNER) == "default"
            TeamResourceGrantsRepository(pg_conn).revoke(
                team_id, "agent", str(agent["id"]), target_user_id=EDITOR
            )
            assert authorized_prompt_id(prompt, OWNER, agent) == "default"

    def test_agent_sources_include_sponsored_and_team_shared(self, app, pg_conn):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        agent, team_id, _, _, source = self._sponsored_agent(app, pg_conn)
        # A source shared with the owner by a team (not owned): used to be
        # dropped by an owner-scoped read.
        shared = str(SourcesRepository(pg_conn).create("shared-src", user_id=OTHER)["id"])
        if not TeamMembersRepository(pg_conn).is_member(OWNER, team_id):
            TeamMembersRepository(pg_conn).add_member(team_id, OWNER)
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "source", shared, OTHER, OTHER)
        AgentsRepository(pg_conn).update_by_id(str(agent["id"]), {"extra_source_ids": [shared]})

        processor = StreamProcessor.__new__(StreamProcessor)
        with _patch_db(pg_conn):
            data = processor._get_data_from_api_key(agent["key"])
        assert [s["id"] for s in data["sources"]] == [source, shared]

    def test_search_service_authorizes_sponsored_source(self, app, pg_conn):
        from docsgpt.services.search_service import _authorized_source_ids

        agent, team_id, _, _, source = self._sponsored_agent(app, pg_conn)
        stranger_src = str(SourcesRepository(pg_conn).create("x", user_id="sp-stranger")["id"])
        assert _authorized_source_ids(pg_conn, agent, [source, stranger_src]) == [source]
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", str(agent["id"]), target_user_id=EDITOR)
        assert _authorized_source_ids(pg_conn, agent, [source]) == []


# ---------------------------------------------------------------------------
# workflows
# ---------------------------------------------------------------------------


def _wf_body(tool=None, source=None):
    agent_cfg = {"agent_type": "classic", "system_prompt": "s", "tools": [tool] if tool else [],
                 "sources": [source] if source else []}
    return {
        "name": "WF",
        "description": "d",
        "nodes": [
            {"id": "start1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "a1", "type": "agent", "title": "A", "position": {"x": 50, "y": 0},
             "data": {"config": agent_cfg}},
            {"id": "end1", "type": "end", "position": {"x": 100, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start1", "target": "a1"},
            {"id": "e2", "source": "a1", "target": "end1"},
        ],
    }


class TestWorkflows:
    def _setup(self, pg_conn):
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        _, team_id = _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        return str(wf["id"]), team_id

    def _put(self, app, pg_conn, wid, user, body):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        return _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", user,
                     json=body, args=(wid,))

    def test_editor_node_resources_are_sponsored(self, app, pg_conn):
        wid, _ = self._setup(pg_conn)
        tool, _, source = _editor_resources(pg_conn)
        resp = self._put(app, pg_conn, wid, EDITOR, _wf_body(tool, source))
        assert _status(resp) == 200, resp.get_json()
        row = WorkflowsRepository(pg_conn).get_by_id(wid)
        assert row["resource_sponsors"] == {
            sponsor_key("tool", tool): EDITOR,
            sponsor_key("source", source): EDITOR,
        }
        # Removing the node's refs clears them.
        assert _status(self._put(app, pg_conn, wid, EDITOR, _wf_body())) == 200
        assert WorkflowsRepository(pg_conn).get_by_id(wid)["resource_sponsors"] == {}

    def test_engine_resolves_sponsored_node_refs(self, app, pg_conn):
        from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

        wid, team_id = self._setup(pg_conn)
        tool, _, source = _editor_resources(pg_conn)
        assert _status(self._put(app, pg_conn, wid, EDITOR, _wf_body(tool, source))) == 200

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.agent = SimpleNamespace(
            workflow_row=WorkflowsRepository(pg_conn).get_by_id(wid),
            _resolve_owner_id=lambda: OWNER,
            user=OWNER,
            decoded_token={"sub": OWNER},
        )
        with _patch_db(pg_conn):
            assert engine._node_tool_principals([tool]) == {tool: EDITOR}
            assert engine._authorized_node_sources([source]) == [source]
            agent_id = str(pg_conn.exec_driver_sql(
                f"SELECT id FROM agents WHERE workflow_id = '{wid}'"
            ).scalar())
            TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
            assert engine._node_tool_principals([tool]) == {}
            assert engine._authorized_node_sources([source]) == []
