"""Role-based access (owner / editor / viewer / stranger) on the agent routes.

Every per-agent endpoint answers through ``resource_access.require``: 404 when
the caller can't see the agent, 403 when their role can't do the action, and
writes land as the agent's owner. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.api.user.resource_access import set_settings, settings_for
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository

OWNER, EDITOR, VIEWER, STRANGER = "r-owner", "r-editor", "r-viewer", "r-stranger"

_DB_MODULES = (
    "docsgpt.api.user.agents.routes",
    "docsgpt.api.user.agents.sharing",
    "docsgpt.api.user.agents.webhooks",
    "docsgpt.api.user.agents.guardrails",
    "docsgpt.api.user.agents.folders",
    "docsgpt.api.user.agents.portability",
    "docsgpt.api.user.schedules.routes",
    "docsgpt.api.user.workflows.routes",
    "docsgpt.api.user.analytics.routes",
    "docsgpt.api.user.base",
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

        request.decoded_token = {"sub": user} if user else None
        return getattr(resource_cls(), method.lower())(*args)


def _status(resp) -> int:
    return resp[1] if isinstance(resp, tuple) else resp.status_code


def _json(resp):
    return resp[0] if isinstance(resp, tuple) else resp.get_json()


def _team_share(conn, resource_type, resource_id, owner=OWNER):
    """Share with a fresh team: EDITOR as editor, VIEWER as viewer."""
    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", owner)
    tid = str(team["id"])
    members = TeamMembersRepository(conn)
    grants = TeamResourceGrantsRepository(conn)
    for member, level in ((EDITOR, "editor"), (VIEWER, "viewer")):
        members.add_member(tid, member)
        grants.grant(tid, resource_type, resource_id, owner, owner,
                     access_level=level, target_user_id=member)
    return tid


def _agent(conn, *, status="published", key="abcd1234wxyz", share=True, **extra):
    extra.setdefault("agent_type", "classic")
    extra.setdefault("chunks", 6)
    row = AgentsRepository(conn).create(
        OWNER, "Shared", status, description="d", key=key, **extra
    )
    agent_id = str(row["id"])
    if share:
        _team_share(conn, "agent", agent_id)
    return agent_id


def _row(conn, agent_id):
    return AgentsRepository(conn).get_by_id(agent_id)


# ---------------------------------------------------------------------------
# get_agent / get_agents
# ---------------------------------------------------------------------------


class TestGetAgent:
    def _get(self, app, conn, agent_id, user):
        from docsgpt.api.user.agents.routes import GetAgent

        return _call(app, conn, GetAgent, "get", f"/api/get_agent?id={agent_id}", user)

    def test_owner_gets_owner_access_and_masked_key(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        data = _json(self._get(app, pg_conn, agent_id, OWNER))
        assert data["access"] == "owner"
        assert "delete" in data["allowed_actions"]
        assert data["key"] == "abcd...wxyz"

    def test_editor_gets_editor_access_and_masked_key(self, app, pg_conn):
        agent_id = _agent(pg_conn, config={"guardrails": {"enabled": True}})
        resp = self._get(app, pg_conn, agent_id, EDITOR)
        assert _status(resp) == 200
        data = _json(resp)
        assert data["access"] == "editor"
        assert data["allowed_actions"] == sorted(data["allowed_actions"])
        assert "edit" in data["allowed_actions"]
        assert "delete" not in data["allowed_actions"]
        assert data["key"] == "abcd...wxyz"
        assert data["config"] == {"guardrails": {"enabled": True}}
        assert data["ownership"] == "team"

    def test_editor_without_access_details_gets_no_key(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        set_settings(pg_conn, "agent", agent_id,
                     {"editors_can_manage_access_details": False}, OWNER)
        data = _json(self._get(app, pg_conn, agent_id, EDITOR))
        assert "key" not in data or data["key"] == ""
        assert data["shared_token"] == ""

    def test_viewer_reads_for_chat_without_secrets_or_policy(self, app, pg_conn):
        agent_id = _agent(pg_conn, config={"guardrails": {"enabled": True}})
        resp = self._get(app, pg_conn, agent_id, VIEWER)
        assert _status(resp) == 200
        data = _json(resp)
        assert data["access"] == "viewer"
        assert data["allowed_actions"] == ["pin", "use"]
        assert data.get("key", "") == ""
        assert data["config"] == {}

    def test_stranger_404(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        assert _status(self._get(app, pg_conn, agent_id, STRANGER)) == 404


class TestGetAgents:
    def test_rows_carry_access(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgents

        shared_id = _agent(pg_conn)
        own = AgentsRepository(pg_conn).create(EDITOR, "Mine", "draft")
        resp = _call(app, pg_conn, GetAgents, "get", "/api/get_agents", EDITOR)
        rows = {r["id"]: r for r in _json(resp)}
        assert rows[str(own["id"])]["access"] == "owner"
        assert "delete" in rows[str(own["id"])]["allowed_actions"]
        assert rows[shared_id]["access"] == "editor"
        assert "edit" in rows[shared_id]["allowed_actions"]
        assert rows[shared_id]["team_access"] == "editor"


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    def _put(self, app, conn, agent_id, user, body):
        from docsgpt.api.user.agents.routes import UpdateAgent

        return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}",
                     user, json=body, args=(agent_id,))

    def test_editor_edits_as_owner(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        resp = self._put(app, pg_conn, agent_id, EDITOR, {"name": "Renamed"})
        assert _status(resp) == 200
        row = _row(pg_conn, agent_id)
        assert row["name"] == "Renamed"
        assert row["user_id"] == OWNER

    def test_viewer_403_stranger_404(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        assert _status(self._put(app, pg_conn, agent_id, VIEWER, {"name": "x"})) == 403
        assert _status(self._put(app, pg_conn, agent_id, STRANGER, {"name": "x"})) == 404

    def test_editor_policy_change_is_applied_not_dropped(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        body = {
            "config": {"guardrails": {"enabled": True}},
            "limited_request_mode": True,
            "request_limit": 7,
        }
        assert _status(self._put(app, pg_conn, agent_id, EDITOR, body)) == 200
        row = _row(pg_conn, agent_id)
        assert row["config"]["guardrails"]["enabled"] is True
        assert row["request_limit"] == 7

    def test_editor_publish_mints_key_and_returns_it(self, app, pg_conn):
        agent_id = _agent(pg_conn, status="draft", key="")
        resp = self._put(app, pg_conn, agent_id, EDITOR, {"status": "published"})
        assert _status(resp) == 200
        assert _json(resp).get("key")

    def test_key_withheld_when_access_details_switch_off(self, app, pg_conn):
        agent_id = _agent(pg_conn, status="draft", key="")
        set_settings(pg_conn, "agent", agent_id,
                     {"editors_can_manage_access_details": False}, OWNER)
        resp = self._put(app, pg_conn, agent_id, EDITOR, {"status": "published"})
        assert _status(resp) == 200
        assert "key" not in _json(resp)
        assert _row(pg_conn, agent_id)["key"]

    def test_editor_cannot_move_folder(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        agent_id = _agent(pg_conn)
        folder = AgentFoldersRepository(pg_conn).create(OWNER, "F")
        resp = self._put(app, pg_conn, agent_id, EDITOR, {"folder_id": str(folder["id"])})
        assert _status(resp) == 403

    def test_editor_saving_unchanged_folder_is_fine(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder = AgentFoldersRepository(pg_conn).create(OWNER, "F")
        agent_id = _agent(pg_conn, folder_id=str(folder["id"]))
        resp = self._put(app, pg_conn, agent_id, EDITOR,
                         {"name": "n", "folder_id": str(folder["id"])})
        assert _status(resp) == 200

    def test_workflow_validated_against_owner_and_owner_only_to_change(self, app, pg_conn):
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        agent_id = _agent(pg_conn, agent_type="workflow")
        # An editor can't point the agent at another of the owner's workflows.
        resp = self._put(app, pg_conn, agent_id, EDITOR, {"workflow": str(wf["id"])})
        assert _status(resp) == 403
        assert _row(pg_conn, agent_id)["workflow_id"] is None

        resp = self._put(app, pg_conn, agent_id, OWNER, {"workflow": str(wf["id"])})
        assert _status(resp) == 200
        assert str(_row(pg_conn, agent_id)["workflow_id"]) == str(wf["id"])
        # Re-sending the current one is a plain save.
        resp = self._put(app, pg_conn, agent_id, EDITOR, {"workflow": str(wf["id"])})
        assert _status(resp) == 200

        mine = WorkflowsRepository(pg_conn).create(EDITOR, "editor-wf")
        resp = self._put(app, pg_conn, agent_id, EDITOR, {"workflow": str(mine["id"])})
        assert _status(resp) == 404

    def test_tool_gate(self, app, pg_conn):
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        tools = UserToolsRepository(pg_conn)
        owner_tool = str(tools.create(OWNER, "api_tool")["id"])
        foreign_tool = str(tools.create(STRANGER, "api_tool")["id"])
        shared_tool = str(tools.create(STRANGER, "api_tool")["id"])
        _team_share(pg_conn, "tool", shared_tool, owner=STRANGER)
        agent_id = _agent(pg_conn)

        # The owner owning a tool isn't enough: it must reach the editor.
        denied = self._put(app, pg_conn, agent_id, EDITOR, {"tools": [owner_tool]})
        assert _status(denied) == 403
        denied = self._put(app, pg_conn, agent_id, EDITOR, {"tools": [foreign_tool]})
        assert _status(denied) == 403
        assert _status(self._put(app, pg_conn, agent_id, OWNER, {"tools": [owner_tool]})) == 200
        ok = self._put(app, pg_conn, agent_id, EDITOR, {"tools": [owner_tool, shared_tool]})
        assert _status(ok) == 200

        set_settings(pg_conn, "tool", shared_tool, {"viewers_can_use_in_agents": False}, STRANGER)
        # Already attached: keeping it is fine.
        assert _status(self._put(app, pg_conn, agent_id, EDITOR,
                                 {"tools": [owner_tool, shared_tool]})) == 200


class TestCreateAgentToolGate:
    def test_foreign_tool_rejected(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import CreateAgent
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        foreign_tool = str(UserToolsRepository(pg_conn).create(STRANGER, "api_tool")["id"])
        body = {"name": "n", "status": "draft", "tools": [foreign_tool]}
        resp = _call(app, pg_conn, CreateAgent, "post", "/api/create_agent", OWNER, json=body)
        assert _status(resp) == 403

    def test_own_tool_accepted(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import CreateAgent
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        body = {"name": "n", "status": "draft", "tools": [tool]}
        resp = _call(app, pg_conn, CreateAgent, "post", "/api/create_agent", OWNER, json=body)
        assert _status(resp) == 201


# ---------------------------------------------------------------------------
# access details: key, webhook, public link
# ---------------------------------------------------------------------------


class TestAccessDetails:
    def _regen(self, app, conn, agent_id, user):
        from docsgpt.api.user.agents.routes import RegenerateAgentKey

        return _call(app, conn, RegenerateAgentKey, "post",
                     f"/api/regenerate_agent_key/{agent_id}", user, args=(agent_id,))

    def test_regenerate_key_roles(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        assert _status(self._regen(app, pg_conn, agent_id, STRANGER)) == 404
        assert _status(self._regen(app, pg_conn, agent_id, VIEWER)) == 403
        resp = self._regen(app, pg_conn, agent_id, EDITOR)
        assert _status(resp) == 200
        assert _row(pg_conn, agent_id)["key"] == _json(resp)["key"]
        set_settings(pg_conn, "agent", agent_id,
                     {"editors_can_manage_access_details": False}, OWNER)
        assert _status(self._regen(app, pg_conn, agent_id, EDITOR)) == 403

    def test_webhook_roles(self, app, pg_conn):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        agent_id = _agent(pg_conn)
        path = f"/api/agent_webhook?id={agent_id}"
        assert _status(_call(app, pg_conn, AgentWebhook, "get", path, VIEWER)) == 403
        assert _status(_call(app, pg_conn, AgentWebhook, "get", path, STRANGER)) == 404
        resp = _call(app, pg_conn, AgentWebhook, "get", path, EDITOR)
        assert _status(resp) == 200
        assert _row(pg_conn, agent_id)["incoming_webhook_token"]

    def test_share_link_roles(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import ShareAgent

        agent_id = _agent(pg_conn)
        body = {"id": agent_id, "shared": True}
        assert _status(_call(app, pg_conn, ShareAgent, "put", "/api/share_agent",
                             VIEWER, json=body)) == 403
        assert _status(_call(app, pg_conn, ShareAgent, "put", "/api/share_agent",
                             STRANGER, json=body)) == 404
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", EDITOR, json=body)
        assert _status(resp) == 200
        assert _row(pg_conn, agent_id)["shared"] is True


# ---------------------------------------------------------------------------
# delete / export / folders
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    def _delete(self, app, conn, agent_id, user):
        from docsgpt.api.user.agents.routes import DeleteAgent

        return _call(app, conn, DeleteAgent, "delete", f"/api/delete_agent?id={agent_id}", user)

    def test_editor_403_by_default(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        assert _status(self._delete(app, pg_conn, agent_id, EDITOR)) == 403
        assert _status(self._delete(app, pg_conn, agent_id, STRANGER)) == 404
        assert _row(pg_conn, agent_id) is not None

    def test_editor_with_switch_deletes_and_settings_go(self, app, pg_conn):
        from sqlalchemy import text

        agent_id = _agent(pg_conn)
        set_settings(pg_conn, "agent", agent_id, {"editors_can_delete": True}, OWNER)
        assert _status(self._delete(app, pg_conn, agent_id, EDITOR)) == 200
        assert _row(pg_conn, agent_id) is None
        assert settings_for(pg_conn, "agent", agent_id)["editors_can_delete"] is False
        left = pg_conn.execute(
            text("SELECT count(*) FROM team_resource_grants WHERE resource_id = CAST(:id AS uuid)"),
            {"id": agent_id},
        ).scalar()
        assert left == 0


class TestExportAgent:
    def test_roles(self, app, pg_conn):
        from docsgpt.api.user.agents.portability import ExportAgent

        agent_id = _agent(pg_conn)
        path = f"/api/export_agent?id={agent_id}"
        assert _status(_call(app, pg_conn, ExportAgent, "get", path, VIEWER)) == 403
        assert _status(_call(app, pg_conn, ExportAgent, "get", path, STRANGER)) == 404
        assert _status(_call(app, pg_conn, ExportAgent, "get", path, EDITOR)) == 200


class TestFolderMoves:
    def test_move_agent_owner_only(self, app, pg_conn):
        from docsgpt.api.user.agents.folders import MoveAgentToFolder

        agent_id = _agent(pg_conn)
        body = {"agent_id": agent_id, "folder_id": None}
        assert _status(_call(app, pg_conn, MoveAgentToFolder, "post",
                             "/api/agents/folders/move_agent", EDITOR, json=body)) == 403
        assert _status(_call(app, pg_conn, MoveAgentToFolder, "post",
                             "/api/agents/folders/move_agent", STRANGER, json=body)) == 404
        assert _status(_call(app, pg_conn, MoveAgentToFolder, "post",
                             "/api/agents/folders/move_agent", OWNER, json=body)) == 200

    def test_bulk_move_reports_skipped(self, app, pg_conn):
        from docsgpt.api.user.agents.folders import BulkMoveAgents
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        shared_id = _agent(pg_conn)
        own = str(AgentsRepository(pg_conn).create(EDITOR, "Mine", "draft")["id"])
        folder = AgentFoldersRepository(pg_conn).create(EDITOR, "F")
        body = {"agent_ids": [own, shared_id], "folder_id": str(folder["id"])}
        resp = _call(app, pg_conn, BulkMoveAgents, "post", "/api/agents/folders/bulk_move",
                     EDITOR, json=body)
        assert _status(resp) == 200
        assert _json(resp)["moved"] == [own]
        assert _json(resp)["skipped"] == [shared_id]
        assert _row(pg_conn, shared_id)["folder_id"] is None


# ---------------------------------------------------------------------------
# pinned / link-shared lists
# ---------------------------------------------------------------------------


class TestListsCarryAccess:
    def test_pinned_agents(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import PinAgent, PinnedAgents

        agent_id = _agent(pg_conn)
        assert _status(_call(app, pg_conn, PinAgent, "post",
                             f"/api/pin_agent?id={agent_id}", VIEWER)) == 200
        rows = _json(_call(app, pg_conn, PinnedAgents, "get", "/api/pinned_agents", VIEWER))
        assert rows[0]["access"] == "viewer"
        assert rows[0]["allowed_actions"] == ["pin", "use"]

    def test_link_shared_agent_is_viewer(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import SharedAgent, SharedAgents

        agent_id = _agent(pg_conn, share=False)
        AgentsRepository(pg_conn).update(agent_id, OWNER, {"shared": True, "shared_token": "tok-r"})
        resp = _call(app, pg_conn, SharedAgent, "get", "/api/shared_agent?token=tok-r", STRANGER)
        data = _json(resp)
        assert data["access"] == "viewer"
        assert data["allowed_actions"] == ["pin", "use"]
        assert "user" not in data
        rows = _json(_call(app, pg_conn, SharedAgents, "get", "/api/shared_agents", STRANGER))
        assert rows[0]["access"] == "viewer"
        assert rows[0]["allowed_actions"] == ["pin", "use"]

    def test_link_shared_agent_with_team_grant_uses_grant(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import SharedAgent

        agent_id = _agent(pg_conn)
        AgentsRepository(pg_conn).update(agent_id, OWNER, {"shared": True, "shared_token": "tok-e"})
        data = _json(_call(app, pg_conn, SharedAgent, "get", "/api/shared_agent?token=tok-e", EDITOR))
        assert data["access"] == "editor"
        assert "edit" in data["allowed_actions"]


# ---------------------------------------------------------------------------
# schedules
# ---------------------------------------------------------------------------


_RUN_NOW_TASK = type("T", (), {"apply_async": staticmethod(lambda **k: None)})


class TestSchedules:
    def _create(self, app, conn, agent_id, user):
        from docsgpt.api.user.schedules.routes import AgentSchedules

        body = {"instruction": "do it", "cron": "0 9 * * *"}
        return _call(app, conn, AgentSchedules, "post", f"/api/agents/{agent_id}/schedules",
                     user, json=body, args=(agent_id,))

    def test_editor_creates_as_owner(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        resp = self._create(app, pg_conn, agent_id, EDITOR)
        assert _status(resp) == 201
        assert _json(resp)["schedule"]["user_id"] == OWNER

    def test_viewer_403_stranger_404(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import AgentSchedules, AgentScheduleStats

        agent_id = _agent(pg_conn)
        assert _status(self._create(app, pg_conn, agent_id, VIEWER)) == 403
        assert _status(self._create(app, pg_conn, agent_id, STRANGER)) == 404
        path = f"/api/agents/{agent_id}/schedules"
        assert _status(_call(app, pg_conn, AgentSchedules, "get", path, VIEWER,
                             args=(agent_id,))) == 403
        assert _status(_call(app, pg_conn, AgentScheduleStats, "get", path + "/stats",
                             VIEWER, args=(agent_id,))) == 403

    def test_editor_manages_owner_schedule(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import (
            AgentSchedules,
            ScheduleResource,
            ScheduleRunList,
            ScheduleRunNow,
        )

        agent_id = _agent(pg_conn)
        sid = _json(self._create(app, pg_conn, agent_id, OWNER))["schedule"]["id"]

        listed = _call(app, pg_conn, AgentSchedules, "get", f"/api/agents/{agent_id}/schedules",
                       EDITOR, args=(agent_id,))
        assert [s["id"] for s in _json(listed)["schedules"]] == [sid]

        path = f"/api/schedules/{sid}"
        assert _status(_call(app, pg_conn, ScheduleResource, "get", path, EDITOR,
                             args=(sid,))) == 200
        assert _status(_call(app, pg_conn, ScheduleResource, "get", path, VIEWER,
                             args=(sid,))) == 403
        assert _status(_call(app, pg_conn, ScheduleResource, "get", path, STRANGER,
                             args=(sid,))) == 404
        put = _call(app, pg_conn, ScheduleResource, "put", path, EDITOR,
                    json={"name": "renamed"}, args=(sid,))
        assert _json(put)["schedule"]["name"] == "renamed"
        patched = _call(app, pg_conn, ScheduleResource, "patch", path, EDITOR,
                        json={"action": "pause"}, args=(sid,))
        assert _json(patched)["schedule"]["status"] == "paused"

        with patch("docsgpt.api.user.tasks.execute_scheduled_run", _RUN_NOW_TASK):
            run = _call(app, pg_conn, ScheduleRunNow, "post", path + "/run", EDITOR, args=(sid,))
        assert _status(run) == 202
        assert _json(run)["run"]["user_id"] == OWNER
        runs = _call(app, pg_conn, ScheduleRunList, "get", path + "/runs", EDITOR, args=(sid,))
        assert len(_json(runs)["runs"]) == 1

        assert _status(_call(app, pg_conn, ScheduleResource, "delete", path, VIEWER,
                             args=(sid,))) == 403
        assert _status(_call(app, pg_conn, ScheduleResource, "delete", path, EDITOR,
                             args=(sid,))) == 200


# ---------------------------------------------------------------------------
# workflows
# ---------------------------------------------------------------------------


def _wf_body(name="WF"):
    return {
        "name": name,
        "description": "d",
        "nodes": [
            {"id": "start1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "end1", "type": "end", "position": {"x": 100, "y": 0}, "data": {}},
        ],
        "edges": [{"id": "e1", "source": "start1", "target": "end1"}],
    }


class TestWorkflows:
    def _setup(self, pg_conn):
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        return str(wf["id"])

    def test_roles(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        wid = self._setup(pg_conn)
        path = f"/api/workflows/{wid}"
        assert _status(_call(app, pg_conn, WorkflowDetail, "get", path, EDITOR, args=(wid,))) == 200
        assert _status(_call(app, pg_conn, WorkflowDetail, "get", path, VIEWER, args=(wid,))) == 403
        assert _status(_call(app, pg_conn, WorkflowDetail, "get", path, STRANGER, args=(wid,))) == 404

        put = _call(app, pg_conn, WorkflowDetail, "put", path, EDITOR,
                    json=_wf_body("Edited"), args=(wid,))
        assert _status(put) == 200
        row = WorkflowsRepository(pg_conn).get_by_id(wid)
        assert row["name"] == "Edited"
        assert row["user_id"] == OWNER
        assert _status(_call(app, pg_conn, WorkflowDetail, "put", path, VIEWER,
                             json=_wf_body(), args=(wid,))) == 403

        assert _status(_call(app, pg_conn, WorkflowDetail, "delete", path, EDITOR,
                             args=(wid,))) == 403
        assert WorkflowsRepository(pg_conn).get_by_id(wid) is not None


# ---------------------------------------------------------------------------
# analytics / logs / guardrail events
# ---------------------------------------------------------------------------


def _seed_conversation(conn, user_id, agent_id, count=2):
    from docsgpt.storage.db.repositories.conversations import ConversationsRepository

    repo = ConversationsRepository(conn)
    conv = repo.create(user_id, name="t", agent_id=agent_id)
    for i in range(count):
        repo.append_message(str(conv["id"]), {"prompt": f"p{i}", "response": f"r{i}"})


class TestAnalytics:
    def _messages(self, app, conn, agent_id, user):
        from docsgpt.api.user.analytics.routes import GetMessageAnalytics

        return _call(app, conn, GetMessageAnalytics, "post", "/api/get_message_analytics",
                     user, json={"api_key_id": agent_id})

    def test_editor_sees_owner_view(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        _seed_conversation(pg_conn, OWNER, agent_id, count=2)
        _seed_conversation(pg_conn, "someone-else", agent_id, count=1)
        resp = self._messages(app, pg_conn, agent_id, EDITOR)
        assert _status(resp) == 200
        assert sum(_json(resp)["messages"].values()) == 3

    def test_viewer_403_unless_switch(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        _seed_conversation(pg_conn, OWNER, agent_id, count=2)
        assert _status(self._messages(app, pg_conn, agent_id, VIEWER)) == 403
        set_settings(pg_conn, "agent", agent_id, {"viewers_can_see_logs": True}, OWNER)
        resp = self._messages(app, pg_conn, agent_id, VIEWER)
        assert _status(resp) == 200
        assert sum(_json(resp)["messages"].values()) == 2

    def test_stranger_gets_empty(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        _seed_conversation(pg_conn, OWNER, agent_id, count=2)
        resp = self._messages(app, pg_conn, agent_id, STRANGER)
        assert _status(resp) == 200
        assert sum(_json(resp)["messages"].values()) == 0

    @pytest.mark.parametrize(
        "cls_name,path",
        [
            ("GetTokenAnalytics", "/api/get_token_analytics"),
            ("GetFeedbackAnalytics", "/api/get_feedback_analytics"),
            ("GetToolAnalytics", "/api/get_tool_analytics"),
            ("GetScheduleAnalytics", "/api/get_schedule_analytics"),
            ("GetUserLogs", "/api/get_user_logs"),
        ],
    )
    def test_other_endpoints_gate_viewer(self, app, pg_conn, cls_name, path):
        from docsgpt.api.user.analytics import routes

        agent_id = _agent(pg_conn)
        cls = getattr(routes, cls_name)
        body = {"api_key_id": agent_id}
        assert _status(_call(app, pg_conn, cls, "post", path, VIEWER, json=body)) == 403
        assert _status(_call(app, pg_conn, cls, "post", path, EDITOR, json=body)) == 200

    def test_logs_editor_sees_owner_chats(self, app, pg_conn):
        from docsgpt.api.user.analytics.routes import GetUserLogs
        from docsgpt.storage.db.repositories.user_logs import UserLogsRepository

        agent_id = _agent(pg_conn)
        UserLogsRepository(pg_conn).insert(
            user_id=OWNER, endpoint="stream",
            data={"agent_id": agent_id, "question": "q", "level": "info"},
        )
        resp = _call(app, pg_conn, GetUserLogs, "post", "/api/get_user_logs", EDITOR,
                     json={"api_key_id": agent_id, "event_type": "chat"})
        assert _status(resp) == 200
        assert len(_json(resp)["logs"]) == 1

    def test_traces_gate(self, app, pg_conn):
        from docsgpt.api.user.analytics.routes import GetTraces

        agent_id = _agent(pg_conn)
        path = f"/api/traces?request_id=r1&api_key_id={agent_id}"
        assert _status(_call(app, pg_conn, GetTraces, "get", path, VIEWER)) == 403
        assert _status(_call(app, pg_conn, GetTraces, "get", path, EDITOR)) == 200


class TestGuardrailEvents:
    def _seed(self, conn, agent_id):
        from docsgpt.storage.db.repositories.guardrail_events import GuardrailEventsRepository

        GuardrailEventsRepository(conn).record_many([
            {
                "user_id": OWNER, "agent_id": agent_id, "stage": "input",
                "check_name": "pii", "detector_type": "regex", "action": "block",
                "outcome": "triggered",
            }
        ])

    def test_events_and_summary(self, app, pg_conn):
        from docsgpt.api.user.agents.guardrails import GuardrailEvents, GuardrailSummary

        agent_id = _agent(pg_conn)
        self._seed(pg_conn, agent_id)
        path = f"/api/guardrails/events?agent_id={agent_id}"
        resp = _call(app, pg_conn, GuardrailEvents, "get", path, EDITOR)
        assert _status(resp) == 200
        assert len(_json(resp)["events"]) == 1
        assert _status(_call(app, pg_conn, GuardrailEvents, "get", path, VIEWER)) == 403
        assert _status(_call(app, pg_conn, GuardrailEvents, "get", path, STRANGER)) == 404

        spath = f"/api/guardrails/summary?agent_id={agent_id}"
        summary = _call(app, pg_conn, GuardrailSummary, "get", spath, EDITOR)
        assert _status(summary) == 200
        assert _json(summary)["totals"]["blocked"] == 1
        assert _status(_call(app, pg_conn, GuardrailSummary, "get", spath, VIEWER)) == 403
