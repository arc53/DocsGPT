"""Tools per workspace, and what a team's tool allows where a personal one asks for its owner.

A team's tools are owned by its principal and reached by team role only; Personal never lists them.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.security.encryption import decrypt_credentials, encrypt_credentials
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def app():
    return Flask(__name__)


def _team(conn, owner="alice", name="Ops", members=(("adam", "team_admin"), ("eddie", "team_editor"),
                                                    ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.tools.routes.db_session", _yield), patch(
        "docsgpt.api.user.tools.routes.db_readonly", _yield
    ), patch("docsgpt.api.user.tools.mcp.db_session", _yield), patch(
        "docsgpt.api.user.tools.mcp.db_readonly", _yield
    ), patch("docsgpt.workspaces.context.db_readonly", _yield), patch(
        "docsgpt.api.user.tools.routes.validate_url"
    ), patch("docsgpt.api.user.tools.mcp.validate_url"):
        yield


def _call(app, conn, resource_cls, user, *, team=None, method="post", json=None, path="/api/x"):
    headers = {WORKSPACE_HEADER: team} if team else {}
    with _patch_db(conn), app.test_request_context(path, method=method.upper(), json=json, headers=headers):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)()


def _tool(conn, owner, name="read_webpage", config=None, status=False, created_by=None, actions=None):
    return UserToolsRepository(conn).create(
        owner, name, config=config or {}, display_name=name, description="",
        actions=actions or [{"name": "act", "active": True, "require_approval": False}], status=status,
        created_by=created_by,
    )


def _row(conn, tool_id, owner):
    return UserToolsRepository(conn).get(str(tool_id), owner)


def _api_config(header_value="sk-secret"):
    return {
        "actions": {
            "get_users": {
                "name": "get_users", "description": "Get users", "url": "https://api.example.com/users",
                "method": "GET", "active": True,
                "headers": {"type": "object", "properties": {
                    "X-Key": {"type": "string", "description": "k", "value": header_value, "filled_by_llm": False},
                }},
                "query_params": {"type": "object", "properties": {}},
                "body": {"type": "object", "properties": {}},
            }
        }
    }


def _list(app, conn, user, team=None):
    from docsgpt.api.user.tools.routes import GetTools

    resp = _call(app, conn, GetTools, user, team=team, method="get", path="/api/get_tools")
    return resp


def _rows(resp):
    return {t["id"]: t for t in resp.json["tools"] if not t.get("default") and not t.get("builtin")}


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------
class TestTeamList:
    def test_lists_only_the_teams_tools_with_the_callers_role(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        other_tid, other_principal = _team(pg_conn, name="Other", members=(("eddie", "team_viewer"),))
        team_tool = _tool(pg_conn, principal, created_by="adam")
        other_team_tool = _tool(pg_conn, other_principal, created_by="alice")
        own = _tool(pg_conn, "eddie", name="brave")
        UsersRepository(pg_conn).upsert("adam", email="adam@example.com")
        UserToolPreferencesRepository(pg_conn).set_in_chat("eddie", str(team_tool["id"]), True)

        resp = _list(app, pg_conn, "eddie", team=tid)
        assert resp.status_code == 200
        rows = _rows(resp)
        assert set(rows) == {str(team_tool["id"])}
        row = rows[str(team_tool["id"])]
        assert row["access"] == "editor" and row["team_role"] == "editor"
        assert row["workspace"] == {"kind": "team", "team_id": tid}
        assert row["origin"] == "team"
        assert {"use", "use_in_own", "edit", "edit_credentials"} <= set(row["allowed_actions"])
        assert "delete" not in row["allowed_actions"]
        # Compat for today's UI: a team row reads like a shared one, named by the team.
        assert row["ownership"] == "team" and row["team_access"] == "editor"
        assert row["owner_label"] == "Ops"
        assert "__team__" not in str(row.get("owner_label"))
        assert row["created_by"] == {"user_id": "adam", "label": "adam@example.com"}
        assert row["in_chat"] is True  # a member's chat switch is their preference, never ``status``
        assert resp.json["workspace"] == {"kind": "team", "team_id": tid, "role": "editor"}
        assert str(own["id"]) not in rows and str(other_team_tool["id"]) not in rows
        # The synthesized defaults are everyone's.
        assert any(t.get("default") for t in resp.json["tools"])

    def test_admin_gets_delete_viewer_gets_use_only(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, created_by="adam")
        admin_row = _rows(_list(app, pg_conn, "adam", team=tid))[str(tool["id"])]
        assert admin_row["access"] == "admin" and "delete" in admin_row["allowed_actions"]
        viewer_row = _rows(_list(app, pg_conn, "vera", team=tid))[str(tool["id"])]
        assert viewer_row["allowed_actions"] == ["use", "use_in_own"]
        assert viewer_row["team_access"] == "viewer"

    def test_team_rows_never_carry_secrets(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, name="mcp_tool", config={
            "server_url": "https://mcp.example.com/mcp", "auth_type": "bearer",
            "encrypted_credentials": encrypt_credentials({"bearer_token": "tok"}, principal),
        })
        row = _rows(_list(app, pg_conn, "adam", team=tid))[str(tool["id"])]
        assert "encrypted_credentials" not in row["config"]
        assert row["config"]["has_encrypted_credentials"] is True

    def test_non_member_header_is_404(self, app, pg_conn):
        tid, _principal = _team(pg_conn)
        resp = _list(app, pg_conn, "stranger", team=tid)
        assert resp.status_code == 404
        assert resp.json["error"] == "workspace_not_found"


class TestPersonalList:
    def test_never_shows_team_items_even_if_a_lookup_returned_one(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_tool = _tool(pg_conn, principal, created_by="adam")
        own = _tool(pg_conn, "eddie", created_by="eddie")
        # Defensive filter: even a grant lookup that wrongly answered a team item is dropped.
        with patch(
            "docsgpt.api.user.tools.routes.visible_with_access",
            return_value={str(team_tool["id"]): "viewer"},
        ):
            resp = _list(app, pg_conn, "eddie")
        rows = _rows(resp)
        assert set(rows) == {str(own["id"])}
        assert rows[str(own["id"])]["workspace"] == {"kind": "personal", "team_id": None}
        assert rows[str(own["id"])]["created_by"] == {"user_id": "eddie", "label": "eddie"}
        assert resp.json["workspace"] == {"kind": "personal", "team_id": None, "role": "owner"}


# ---------------------------------------------------------------------------
# Creates
# ---------------------------------------------------------------------------
def _create(app, conn, user, body, team=None):
    from docsgpt.api.user.tools.routes import CreateTool

    return _call(app, conn, CreateTool, user, team=team, json=body)


def _body(name="read_webpage", config=None, status=True):
    return {"name": name, "displayName": name, "description": "", "config": config or {}, "status": status}


class TestTeamCreate:
    def test_editor_creates_a_principal_owned_tool_and_is_its_creator(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, "eddie", _body(status=True), team=tid)
        assert resp.status_code == 200, resp.json
        row = _row(pg_conn, resp.json["id"], principal)
        assert row is not None and row["created_by"] == "eddie"
        # ``status`` is never a member's switch on a team tool; the creator's choice is their preference.
        assert row["status"] is False
        prefs = UserToolPreferencesRepository(pg_conn).in_chat_many("eddie", [resp.json["id"]])
        assert prefs[resp.json["id"]] is True
        assert UserToolsRepository(pg_conn).list_for_user("eddie") == []

    def test_viewer_cannot_create(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, "vera", _body(), team=tid)
        assert resp.status_code == 403
        assert resp.json["error"] == "workspace_role_required"
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_non_member_cannot_create(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, "stranger", _body(), team=tid)
        assert resp.status_code == 404
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_secrets_are_sealed_under_the_principal_and_decrypt_at_run(self, app, pg_conn):
        from docsgpt.agents.tool_executor import api_tool_action_with_secrets

        tid, principal = _team(pg_conn)
        body = _body(name="api_tool", config=_api_config("sk-team"))
        resp = _create(app, pg_conn, "eddie", body, team=tid)
        assert resp.status_code == 200, resp.json
        row = _row(pg_conn, resp.json["id"], principal)
        # The run decrypts with the row's owner (the principal), whoever chats.
        action = api_tool_action_with_secrets(row, "get_users", "eddie")
        assert action["headers"]["properties"]["X-Key"]["value"] == "sk-team"
        # Bound to the principal: the creator's own key can't open it.
        from docsgpt.agents.tool_executor import API_TOOL_SECRETS_KEY

        blob = row["config"][API_TOOL_SECRETS_KEY]
        assert decrypt_credentials(blob, principal) and decrypt_credentials(blob, "eddie") == {}

    def test_remote_device_is_personal_only(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, "adam", _body(name="remote_device", config={"device_id": "d1"}), team=tid)
        assert resp.status_code == 403
        assert resp.json["error"] == "remote_device_personal_only"
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_connected_service_tool_is_personal_only(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, "adam", _body(name="telegram", config={"token": "t"}), team=tid)
        assert resp.status_code == 403
        assert resp.json["error"] == "connector_personal_only"
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []
        count = pg_conn.execute(
            text("SELECT count(*) FROM connector_sessions WHERE user_id = :p"), {"p": principal}
        ).scalar()
        assert count == 0


class TestPersonalCreate:
    def test_personal_create_records_the_creator(self, app, pg_conn):
        resp = _create(app, pg_conn, "eddie", _body())
        assert resp.status_code == 200
        assert _row(pg_conn, resp.json["id"], "eddie")["created_by"] == "eddie"


# ---------------------------------------------------------------------------
# Edits by id, and the places a personal tool asks for its owner
# ---------------------------------------------------------------------------
def _pinned_actions():
    return [{
        "name": "send", "active": True, "require_approval": False,
        "parameters": {"type": "object", "properties": {
            "server_url": {"type": "string", "filled_by_llm": False, "value": "https://ntfy.example.com"},
            "message": {"type": "string", "filled_by_llm": True, "value": ""},
        }},
    }]


def _moved(actions):
    import copy

    out = copy.deepcopy(actions)
    out[0]["parameters"]["properties"]["server_url"]["value"] = "https://other.example"
    return out


class TestOwnerSites:
    def test_team_editor_may_change_fixed_values_viewer_may_not(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool, UpdateToolActions

        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, name="ntfy", actions=_pinned_actions(), created_by="adam")
        body = {"id": str(tool["id"]), "actions": _moved(tool["actions"])}
        assert _call(app, pg_conn, UpdateToolActions, "vera", json=body).status_code == 403
        assert _call(app, pg_conn, UpdateToolActions, "eddie", json=body).status_code == 200
        pinned = _row(pg_conn, tool["id"], principal)["actions"][0]["parameters"]["properties"]["server_url"]
        assert pinned["value"] == "https://other.example"
        back = {"id": str(tool["id"]), "actions": tool["actions"]}
        assert _call(app, pg_conn, UpdateTool, "eddie", json=back).status_code == 200

    def test_team_editor_may_change_api_tool_fixed_values(self, app, pg_conn):
        from docsgpt.agents.tool_executor import api_tool_action_with_secrets
        from docsgpt.api.user.tools.routes import UpdateToolConfig, _seal_api_tool_secrets

        tid, principal = _team(pg_conn)
        sealed = _seal_api_tool_secrets(_api_config("old"), {}, principal)
        tool = _tool(pg_conn, principal, name="api_tool", config=sealed, created_by="adam")
        body = {"id": str(tool["id"]), "config": _api_config("new")}
        assert _call(app, pg_conn, UpdateToolConfig, "vera", json=body).status_code == 403
        resp = _call(app, pg_conn, UpdateToolConfig, "eddie", json=body)
        assert resp.status_code == 200, resp.json
        row = _row(pg_conn, tool["id"], principal)
        assert api_tool_action_with_secrets(row, "get_users")["headers"]["properties"]["X-Key"]["value"] == "new"

    def test_oauth_server_config_is_refused_even_for_the_teams_admin(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolConfig

        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, name="mcp_tool",
                     config={"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth"})
        body = {"id": str(tool["id"]), "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth"}}
        assert _call(app, pg_conn, UpdateToolConfig, "alice", json=body).status_code == 403

    def test_status_is_the_members_preference_never_the_row(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool, UpdateToolStatus

        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, status=False)
        for user in ("vera", "alice"):
            resp = _call(app, pg_conn, UpdateToolStatus, user, json={"id": str(tool["id"]), "status": True})
            assert resp.status_code == 200
        assert _call(app, pg_conn, UpdateTool, "eddie", json={"id": str(tool["id"]), "status": True}).status_code == 200
        assert _row(pg_conn, tool["id"], principal)["status"] is False
        prefs = UserToolPreferencesRepository(pg_conn)
        for user in ("vera", "alice", "eddie"):
            assert prefs.in_chat_many(user, [str(tool["id"])])[str(tool["id"])] is True

    def test_edit_writes_as_the_principal(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal)
        body = {"id": str(tool["id"]), "customName": "Renamed"}
        assert _call(app, pg_conn, UpdateTool, "vera", json=body).status_code == 403
        assert _call(app, pg_conn, UpdateTool, "eddie", json=body).status_code == 200
        assert _row(pg_conn, tool["id"], principal)["custom_name"] == "Renamed"

    def test_delete_needs_admin(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import DeleteTool

        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal)
        assert _call(app, pg_conn, DeleteTool, "eddie", json={"id": str(tool["id"])}).status_code == 403
        assert _call(app, pg_conn, DeleteTool, "stranger", json={"id": str(tool["id"])}).status_code == 404
        assert _call(app, pg_conn, DeleteTool, "adam", json={"id": str(tool["id"])}).status_code == 200
        assert _row(pg_conn, tool["id"], principal) is None


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------
class TestTeamMCP:
    def _save(self, app, conn, user, body, team=None):
        from docsgpt.api.user.tools.mcp import MCPServerSave

        fake = MagicMock()
        fake.get_actions_metadata.return_value = [{"name": "t1"}]
        with patch("docsgpt.api.user.tools.mcp.MCPTool", return_value=fake) as cls, patch(
            "docsgpt.api.user.tools.mcp._mcp_policy_error", return_value=None
        ):
            resp = _call(app, conn, MCPServerSave, user, team=team, json=body)
        return resp, cls

    def _bearer(self, token="tok"):
        return {"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer", "transport_type": "http",
                "bearer_token": token}

    def test_editor_saves_a_team_server_sealed_under_the_principal_without_a_connection(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp, cls = self._save(app, pg_conn, "eddie", {"displayName": "M", "config": self._bearer()}, team=tid)
        assert resp.status_code == 200, resp.json
        row = _row(pg_conn, resp.json["id"], principal)
        assert row["created_by"] == "eddie" and row["status"] is False
        assert row["connection_id"] is None
        assert decrypt_credentials(row["config"]["encrypted_credentials"], principal) == {"bearer_token": "tok"}
        assert cls.call_args.kwargs["user_id"] == principal
        count = pg_conn.execute(
            text("SELECT count(*) FROM connector_sessions WHERE user_id = :p"), {"p": principal}
        ).scalar()
        assert count == 0  # no team connections in v1

    def test_editor_update_of_a_team_server_keeps_no_connection(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, name="mcp_tool", config={
            "server_url": "https://mcp.example.com/mcp", "auth_type": "bearer", "transport_type": "http",
            "encrypted_credentials": encrypt_credentials({"bearer_token": "tok"}, principal),
        })
        body = {"id": str(tool["id"]), "displayName": "Renamed",
                "config": {k: v for k, v in self._bearer().items() if k != "bearer_token"}}
        resp, _cls = self._save(app, pg_conn, "eddie", body)
        assert resp.status_code == 200, resp.json
        row = _row(pg_conn, tool["id"], principal)
        assert row["display_name"] == "Renamed" and row["connection_id"] is None
        assert decrypt_credentials(row["config"]["encrypted_credentials"], principal) == {"bearer_token": "tok"}

    def test_a_new_team_server_is_filed_in_the_teams_folder(self, app, pg_conn):
        from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository

        tid, principal = _team(pg_conn)
        folder = str(FoldersRepository(pg_conn).create(principal, "Servers", resource_type="tool")["id"])
        body = {"displayName": "M", "config": self._bearer(), "folder_id": folder}
        resp, _cls = self._save(app, pg_conn, "eddie", body, team=tid)
        assert resp.status_code == 200, resp.json
        assert FolderItemsRepository(pg_conn).filing(principal, "tool", resp.json["id"]) == folder

    def test_a_new_team_server_cant_go_in_the_callers_own_folder(self, app, pg_conn):
        from docsgpt.storage.db.repositories.folders import FoldersRepository

        tid, principal = _team(pg_conn)
        own = str(FoldersRepository(pg_conn).create("eddie", "Mine", resource_type="tool")["id"])
        body = {"displayName": "M", "config": self._bearer(), "folder_id": own}
        resp, cls = self._save(app, pg_conn, "eddie", body, team=tid)
        assert resp.status_code == 404
        assert resp.json["error"] == "folder_not_found"
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []
        cls.assert_not_called()

    def test_a_new_personal_server_is_filed_in_the_callers_folder(self, app, pg_conn):
        from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository

        folder = str(FoldersRepository(pg_conn).create("eddie", "Mine", resource_type="tool")["id"])
        body = {"displayName": "M", "config": self._bearer(), "folder_id": folder}
        resp, _cls = self._save(app, pg_conn, "eddie", body)
        assert resp.status_code == 200, resp.json
        assert FolderItemsRepository(pg_conn).filing("eddie", "tool", resp.json["id"]) == folder

    def test_an_update_files_and_unfiles_a_team_server_in_the_teams_tree(self, app, pg_conn):
        from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository

        tid, principal = _team(pg_conn)
        folder = str(FoldersRepository(pg_conn).create(principal, "Servers", resource_type="tool")["id"])
        tool = _tool(pg_conn, principal, name="mcp_tool", config={
            "server_url": "https://mcp.example.com/mcp", "auth_type": "bearer", "transport_type": "http",
            "encrypted_credentials": encrypt_credentials({"bearer_token": "tok"}, principal),
        })
        config = {k: v for k, v in self._bearer().items() if k != "bearer_token"}
        body = {"id": str(tool["id"]), "displayName": "M", "config": config, "folder_id": folder}
        resp, _cls = self._save(app, pg_conn, "eddie", body)
        assert resp.status_code == 200, resp.json
        assert FolderItemsRepository(pg_conn).filing(principal, "tool", str(tool["id"])) == folder
        assert FolderItemsRepository(pg_conn).filing("eddie", "tool", str(tool["id"])) is None

        resp, _cls = self._save(app, pg_conn, "eddie", {**body, "folder_id": None})
        assert resp.status_code == 200, resp.json
        assert FolderItemsRepository(pg_conn).filing(principal, "tool", str(tool["id"])) is None

    def test_an_update_cant_file_a_team_server_in_a_personal_folder(self, app, pg_conn):
        from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository

        tid, principal = _team(pg_conn)
        own = str(FoldersRepository(pg_conn).create("eddie", "Mine", resource_type="tool")["id"])
        tool = _tool(pg_conn, principal, name="mcp_tool", config={
            "server_url": "https://mcp.example.com/mcp", "auth_type": "bearer", "transport_type": "http",
            "encrypted_credentials": encrypt_credentials({"bearer_token": "tok"}, principal),
        })
        config = {k: v for k, v in self._bearer().items() if k != "bearer_token"}
        body = {"id": str(tool["id"]), "displayName": "Renamed", "config": config, "folder_id": own}
        resp, _cls = self._save(app, pg_conn, "eddie", body)
        assert resp.status_code == 404
        assert FolderItemsRepository(pg_conn).filing("eddie", "tool", str(tool["id"])) is None
        assert _row(pg_conn, tool["id"], principal)["display_name"] != "Renamed"

    def test_viewer_cannot_save_in_a_team(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp, _cls = self._save(app, pg_conn, "vera", {"displayName": "M", "config": self._bearer()}, team=tid)
        assert resp.status_code == 403
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_oauth_server_is_personal_only(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        config = {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth", "transport_type": "http",
                  "oauth_task_id": "task-1"}
        resp, _cls = self._save(app, pg_conn, "adam", {"displayName": "M", "config": config}, team=tid)
        assert resp.status_code == 403
        assert resp.json["error"] == "oauth_personal_only"
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_oauth_test_is_personal_only(self, app, pg_conn):
        from docsgpt.api.user.tools.mcp import TestMCPServerConfig

        tid, _principal = _team(pg_conn)
        config = {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth", "transport_type": "http"}
        with patch("docsgpt.api.user.tools.mcp.MCPTool") as cls, patch(
            "docsgpt.api.user.tools.mcp._mcp_policy_error", return_value=None
        ):
            resp = _call(app, pg_conn, TestMCPServerConfig, "adam", team=tid, json={"config": config})
        assert resp.status_code == 403
        assert resp.json["error"] == "oauth_personal_only"
        cls.assert_not_called()

    def test_auth_status_lists_the_workspaces_servers(self, app, pg_conn):
        from docsgpt.api.user.tools.mcp import MCPAuthStatus

        tid, principal = _team(pg_conn)
        team_tool = _tool(pg_conn, principal, name="mcp_tool",
                          config={"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer"})
        own = _tool(pg_conn, "eddie", name="mcp_tool",
                    config={"server_url": "https://mine.example.com/mcp", "auth_type": "bearer"})
        team_resp = _call(app, pg_conn, MCPAuthStatus, "eddie", team=tid, method="get")
        assert set(team_resp.json["statuses"]) == {str(team_tool["id"])}
        personal = _call(app, pg_conn, MCPAuthStatus, "eddie", method="get")
        assert set(personal.json["statuses"]) == {str(own["id"])}
