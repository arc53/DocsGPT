"""Roles on tools: listing payload, write actions, secrets, chat preferences, MCP save."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.api.user.resource_access import set_settings
from docsgpt.security.encryption import decrypt_credentials, encrypt_credentials
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import (
    UserToolPreferencesRepository,
)
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository

OWNER = "alice"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.tools.routes.db_session", _yield), patch(
        "docsgpt.api.user.tools.routes.db_readonly", _yield
    ), patch("docsgpt.api.user.tools.mcp.db_session", _yield), patch(
        "docsgpt.api.user.tools.mcp.db_readonly", _yield
    ), patch("docsgpt.api.user.tools.routes.validate_url"), patch(
        "docsgpt.api.user.tools.mcp.validate_url"
    ):
        # URL validation resolves DNS; the SSRF gate has its own tests.
        yield


def _call(app, conn, resource_cls, user, *, method="post", json=None, path="/api/x"):
    with _patch_db(conn), app.test_request_context(path, method=method.upper(), json=json):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)()


def _share(conn, tool_id, member, level, *, team_name="Acme"):
    team = TeamsRepository(conn).create(team_name, f"t-{uuid.uuid4().hex[:8]}", OWNER)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), "tool", str(tool_id), OWNER, OWNER, access_level=level
    )
    return team


def _tool(conn, name="read_webpage", config=None, status=True, owner=OWNER):
    return UserToolsRepository(conn).create(
        owner, name, config=config or {}, display_name=name, description="",
        actions=[{"name": "act", "active": True, "require_approval": False}], status=status,
    )


def _api_config(url="https://api.example.com/users", header_value="sk-secret", query_value="q-secret"):
    return {
        "actions": {
            "get_users": {
                "name": "get_users",
                "description": "Get users",
                "url": url,
                "method": "GET",
                "active": True,
                "headers": {"type": "object", "properties": {
                    "X-Key": {"type": "string", "description": "k", "value": header_value,
                              "filled_by_llm": False},
                }},
                "query_params": {"type": "object", "properties": {
                    "token": {"type": "string", "description": "t", "value": query_value,
                              "filled_by_llm": False},
                    "limit": {"type": "integer", "description": "l", "value": "", "filled_by_llm": True},
                }},
                "body": {"type": "object", "properties": {}},
            }
        }
    }


def _row(conn, tool_id, owner=OWNER):
    return UserToolsRepository(conn).get(str(tool_id), owner)


def _runtime_action(conn, tool_id, owner=OWNER):
    from docsgpt.agents.tool_executor import api_tool_action_with_secrets

    row = _row(conn, tool_id, owner)
    return api_tool_action_with_secrets(row, "get_users", owner)


# ---------------------------------------------------------------------------
# 1. GET /api/get_tools
# ---------------------------------------------------------------------------
class TestGetToolsAccess:
    def _tools(self, app, conn, user):
        from docsgpt.api.user.tools.routes import GetTools

        resp = _call(app, conn, GetTools, user, method="get", path="/api/get_tools")
        assert resp.status_code == 200
        return {t["id"]: t for t in resp.json["tools"] if not t.get("default") and not t.get("builtin")}

    def test_owner_row_carries_owner_payload_and_in_chat_from_status(self, app, pg_conn):
        tool = _tool(pg_conn, status=False)
        row = self._tools(app, pg_conn, OWNER)[str(tool["id"])]
        assert row["access"] == "owner"
        assert {"delete", "share", "manage_settings", "edit"} <= set(row["allowed_actions"])
        assert row["allowed_actions"] == sorted(row["allowed_actions"])
        assert row["in_chat"] is False
        assert row["ownership"] == "user"

    def test_viewer_row_payload_shared_via_owner_label_and_preference(self, app, pg_conn):
        UsersRepository(pg_conn).upsert(OWNER, email="alice@example.com")
        tool = _tool(pg_conn)
        _share(pg_conn, tool["id"], "bob", "viewer", team_name="Research")
        row = self._tools(app, pg_conn, "bob")[str(tool["id"])]
        assert row["access"] == "viewer"
        assert row["allowed_actions"] == ["use", "use_in_own"]
        assert row["in_chat"] is False  # sharing never adds to chats
        assert row["shared_via"] == "Research"
        assert row["owner_label"] == "alice@example.com"
        assert row["ownership"] == "team" and row["team_access"] == "viewer"

        UserToolPreferencesRepository(pg_conn).set_in_chat("bob", str(tool["id"]), True)
        assert self._tools(app, pg_conn, "bob")[str(tool["id"])]["in_chat"] is True

    def test_owner_label_null_without_user_row(self, app, pg_conn):
        tool = _tool(pg_conn)
        _share(pg_conn, tool["id"], "bob", "editor")
        row = self._tools(app, pg_conn, "bob")[str(tool["id"])]
        assert row["owner_label"] is None
        assert "edit" in row["allowed_actions"] and "delete" not in row["allowed_actions"]

    def test_default_rows_carry_in_chat(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import GetTools

        resp = _call(app, pg_conn, GetTools, OWNER, method="get", path="/api/get_tools")
        defaults = [t for t in resp.json["tools"] if t.get("default")]
        assert all(t["in_chat"] == t["status"] for t in defaults)

    def test_api_tool_secret_values_masked_for_owner_and_grantee(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import _seal_api_tool_secrets

        sealed = _seal_api_tool_secrets(_api_config(), {}, OWNER)
        tool = _tool(pg_conn, name="api_tool", config=sealed)
        _share(pg_conn, tool["id"], "bob", "viewer")
        for user in (OWNER, "bob"):
            row = self._tools(app, pg_conn, user)[str(tool["id"])]
            action = row["config"]["actions"]["get_users"]
            header = action["headers"]["properties"]["X-Key"]
            assert header["value"] == "" and header["has_value"] is True
            token = action["query_params"]["properties"]["token"]
            assert token["value"] == "" and token["has_value"] is True
            limit = action["query_params"]["properties"]["limit"]
            assert limit["value"] == "" and limit.get("has_value") is False
            assert "encrypted_action_secrets" not in row["config"]
            assert "encrypted_credentials" not in row["config"]

    def test_legacy_plaintext_api_tool_values_masked(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config=_api_config())
        row = self._tools(app, pg_conn, OWNER)[str(tool["id"])]
        header = row["config"]["actions"]["get_users"]["headers"]["properties"]["X-Key"]
        assert header == {**header, "value": "", "has_value": True}


# ---------------------------------------------------------------------------
# 2. api_tool secret storage
# ---------------------------------------------------------------------------
class TestApiToolSecrets:
    def _save(self, app, conn, user, tool_id, config):
        from docsgpt.api.user.tools.routes import UpdateTool

        return _call(app, conn, UpdateTool, user, json={"id": str(tool_id), "config": config})

    def _masked(self, config):
        import copy

        out = copy.deepcopy(config)
        for section in ("headers", "query_params"):
            for spec in out["actions"]["get_users"][section]["properties"].values():
                spec["has_value"] = bool(spec.get("value"))
                spec["value"] = ""
        return out

    def test_values_stored_encrypted_not_plaintext(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config={})
        assert self._save(app, pg_conn, OWNER, tool["id"], _api_config()).status_code == 200
        stored = _row(pg_conn, tool["id"])["config"]
        header = stored["actions"]["get_users"]["headers"]["properties"]["X-Key"]
        assert header["value"] == ""
        assert stored["encrypted_action_secrets"]
        blob = decrypt_credentials(stored["encrypted_action_secrets"], OWNER)
        assert blob["get_users"]["headers"]["X-Key"] == "sk-secret"
        action = _runtime_action(pg_conn, tool["id"])
        assert action["headers"]["properties"]["X-Key"]["value"] == "sk-secret"
        assert action["query_params"]["properties"]["token"]["value"] == "q-secret"

    def test_empty_value_with_has_value_keeps_stored_secret(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config={})
        self._save(app, pg_conn, OWNER, tool["id"], _api_config())
        masked = self._masked(_api_config())
        masked["actions"]["get_users"]["description"] = "Renamed"
        assert self._save(app, pg_conn, OWNER, tool["id"], masked).status_code == 200
        action = _runtime_action(pg_conn, tool["id"])
        assert action["description"] == "Renamed"
        assert action["headers"]["properties"]["X-Key"]["value"] == "sk-secret"

    def test_new_value_replaces_and_cleared_has_value_drops(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config={})
        self._save(app, pg_conn, OWNER, tool["id"], _api_config())
        cfg = self._masked(_api_config())
        cfg["actions"]["get_users"]["headers"]["properties"]["X-Key"]["value"] = "sk-new"
        cfg["actions"]["get_users"]["query_params"]["properties"]["token"]["has_value"] = False
        self._save(app, pg_conn, OWNER, tool["id"], cfg)
        action = _runtime_action(pg_conn, tool["id"])
        assert action["headers"]["properties"]["X-Key"]["value"] == "sk-new"
        assert action["query_params"]["properties"]["token"]["value"] == ""

    def test_legacy_plaintext_reencrypted_on_save(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config=_api_config())
        # Runtime reads the legacy plaintext value transparently.
        assert _runtime_action(pg_conn, tool["id"])["headers"]["properties"]["X-Key"]["value"] == "sk-secret"
        self._save(app, pg_conn, OWNER, tool["id"], self._masked(_api_config()))
        stored = _row(pg_conn, tool["id"])["config"]
        assert stored["actions"]["get_users"]["headers"]["properties"]["X-Key"]["value"] == ""
        assert _runtime_action(pg_conn, tool["id"])["headers"]["properties"]["X-Key"]["value"] == "sk-secret"

    def test_editor_save_encrypts_with_owner_key(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config={})
        _share(pg_conn, tool["id"], "bob", "editor")
        assert self._save(app, pg_conn, "bob", tool["id"], _api_config()).status_code == 200
        stored = _row(pg_conn, tool["id"])["config"]
        assert decrypt_credentials(stored["encrypted_action_secrets"], OWNER)
        assert UserToolsRepository(pg_conn).list_for_user("bob") == []

    def test_url_host_change_clears_secrets_and_requires_new_ones(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config={})
        self._save(app, pg_conn, OWNER, tool["id"], _api_config())
        moved = self._masked(_api_config(url="https://evil.example.org/users"))
        resp = self._save(app, pg_conn, OWNER, tool["id"], moved)
        assert resp.status_code == 400
        assert "credentials" in resp.json["message"].lower()
        # Same host, different path: stored values kept.
        same_host = self._masked(_api_config(url="https://api.example.com/v2/users"))
        assert self._save(app, pg_conn, OWNER, tool["id"], same_host).status_code == 200
        assert _runtime_action(pg_conn, tool["id"])["headers"]["properties"]["X-Key"]["value"] == "sk-secret"

    @pytest.mark.parametrize("url", [
        "http://api.example.com/users",        # https -> http: cleartext
        "https://api.example.com:8443/users",  # another port, maybe another service
    ])
    def test_url_scheme_or_port_change_requires_new_secrets(self, app, pg_conn, url):
        tool = _tool(pg_conn, name="api_tool", config={})
        self._save(app, pg_conn, OWNER, tool["id"], _api_config())
        resp = self._save(app, pg_conn, OWNER, tool["id"], self._masked(_api_config(url=url)))
        assert resp.status_code == 400
        assert "credentials" in resp.json["message"].lower()

    def test_url_with_explicit_default_port_keeps_secrets(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config={})
        self._save(app, pg_conn, OWNER, tool["id"], _api_config())
        same = self._masked(_api_config(url="https://API.example.com:443/users"))
        assert self._save(app, pg_conn, OWNER, tool["id"], same).status_code == 200
        assert _runtime_action(pg_conn, tool["id"])["headers"]["properties"]["X-Key"]["value"] == "sk-secret"

    def test_url_host_change_with_new_secrets_succeeds(self, app, pg_conn):
        tool = _tool(pg_conn, name="api_tool", config={})
        self._save(app, pg_conn, OWNER, tool["id"], _api_config())
        moved = _api_config(url="https://other.example.org/users", header_value="sk-2", query_value="q-2")
        assert self._save(app, pg_conn, OWNER, tool["id"], moved).status_code == 200
        action = _runtime_action(pg_conn, tool["id"])
        assert action["headers"]["properties"]["X-Key"]["value"] == "sk-2"


# ---------------------------------------------------------------------------
# 3. Write actions
# ---------------------------------------------------------------------------
class TestToolWrites:
    def test_update_tool_rename_by_role(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        tool = _tool(pg_conn)
        _share(pg_conn, tool["id"], "ed", "editor")
        _share(pg_conn, tool["id"], "vi", "viewer")
        body = {"id": str(tool["id"]), "customName": "Renamed"}
        assert _call(app, pg_conn, UpdateTool, "ed", json=body).status_code == 200
        assert _row(pg_conn, tool["id"])["custom_name"] == "Renamed"
        resp = _call(app, pg_conn, UpdateTool, "vi", json=body)
        assert resp.status_code == 403 and resp.json["success"] is False
        assert _call(app, pg_conn, UpdateTool, "stranger", json=body).status_code == 404

    def test_update_tool_config_needs_edit_credentials(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool, UpdateToolConfig

        tool = _tool(pg_conn, name="brave", config={})
        _share(pg_conn, tool["id"], "ed", "editor")
        set_settings(pg_conn, "tool", str(tool["id"]), {"editors_can_change_credentials": False}, OWNER)
        body = {"id": str(tool["id"]), "config": {"token": "x"}}
        assert _call(app, pg_conn, UpdateToolConfig, "ed", json=body).status_code == 403
        assert _call(app, pg_conn, UpdateTool, "ed", json=body).status_code == 403
        set_settings(pg_conn, "tool", str(tool["id"]), {"editors_can_change_credentials": True}, OWNER)
        assert _call(app, pg_conn, UpdateToolConfig, "ed", json=body).status_code == 200

    def test_update_tool_config_encrypts_with_owner_key(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolConfig

        tool = _tool(pg_conn, name="mcp_tool", config={"server_url": "https://mcp.example.com/x",
                                                         "auth_type": "bearer"})
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "config": {"server_url": "https://mcp.example.com/x",
                                                  "auth_type": "bearer", "bearer_token": "tok"}}
        assert _call(app, pg_conn, UpdateToolConfig, "ed", json=body).status_code == 200
        stored = _row(pg_conn, tool["id"])["config"]
        assert decrypt_credentials(stored["encrypted_credentials"], OWNER) == {"bearer_token": "tok"}

    def test_update_tool_config_host_change_clears_stored_secrets(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolConfig

        cfg = {"server_url": "https://mcp.example.com/x", "auth_type": "bearer",
               "encrypted_credentials": encrypt_credentials({"bearer_token": "tok"}, OWNER)}
        tool = _tool(pg_conn, name="mcp_tool", config=cfg)
        body = {"id": str(tool["id"]), "config": {"server_url": "https://other.example.org/x",
                                                  "auth_type": "bearer"}}
        resp = _call(app, pg_conn, UpdateToolConfig, OWNER, json=body)
        assert resp.status_code == 400
        assert "credentials" in resp.json["message"].lower()
        stored = _row(pg_conn, tool["id"])["config"]
        assert stored["server_url"] == "https://mcp.example.com/x"

    def test_update_tool_config_scheme_change_clears_stored_secrets(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolConfig

        cfg = {"server_url": "https://mcp.example.com/x", "auth_type": "bearer",
               "encrypted_credentials": encrypt_credentials({"bearer_token": "tok"}, OWNER)}
        tool = _tool(pg_conn, name="mcp_tool", config=cfg)
        body = {"id": str(tool["id"]), "config": {"server_url": "http://mcp.example.com/x",
                                                  "auth_type": "bearer"}}
        resp = _call(app, pg_conn, UpdateToolConfig, OWNER, json=body)
        assert resp.status_code == 400
        assert _row(pg_conn, tool["id"])["config"]["server_url"] == "https://mcp.example.com/x"

    def test_api_tool_description_edit_needs_only_edit(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool, _seal_api_tool_secrets

        tool = _tool(pg_conn, name="api_tool", config=_seal_api_tool_secrets(_api_config(), {}, OWNER))
        _share(pg_conn, tool["id"], "ed", "editor")
        set_settings(pg_conn, "tool", str(tool["id"]), {"editors_can_change_credentials": False}, OWNER)
        cfg = TestApiToolSecrets()._masked(_api_config())
        cfg["actions"]["get_users"]["description"] = "Edited"
        body = {"id": str(tool["id"]), "config": cfg}
        assert _call(app, pg_conn, UpdateTool, "ed", json=body).status_code == 200
        # Changing the URL (or a secret value) needs edit_credentials.
        cfg["actions"]["get_users"]["url"] = "https://api.example.com/v2"
        assert _call(app, pg_conn, UpdateTool, "ed", json=body).status_code == 403

    def test_update_tool_actions_by_role(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolActions

        tool = _tool(pg_conn)
        _share(pg_conn, tool["id"], "ed", "editor")
        _share(pg_conn, tool["id"], "vi", "viewer")
        actions = [{"name": "act", "active": True, "require_approval": True}]
        body = {"id": str(tool["id"]), "actions": actions}
        assert _call(app, pg_conn, UpdateToolActions, "ed", json=body).status_code == 200
        assert _row(pg_conn, tool["id"])["actions"][0]["require_approval"] is True
        assert _call(app, pg_conn, UpdateToolActions, "vi", json=body).status_code == 403
        assert _call(app, pg_conn, UpdateToolActions, "nobody", json=body).status_code == 404

    def test_delete_tool_by_role_cleans_grants_and_settings(self, app, pg_conn):
        from sqlalchemy import text

        from docsgpt.api.user.tools.routes import DeleteTool

        tool = _tool(pg_conn)
        tid = str(tool["id"])
        _share(pg_conn, tid, "ed", "editor")
        set_settings(pg_conn, "tool", tid, {"editors_can_share": True}, OWNER)
        assert _call(app, pg_conn, DeleteTool, "ed", json={"id": tid}).status_code == 403
        assert _call(app, pg_conn, DeleteTool, "nobody", json={"id": tid}).status_code == 404
        assert _call(app, pg_conn, DeleteTool, OWNER, json={"id": tid}).status_code == 200
        assert _row(pg_conn, tid) is None
        grants = pg_conn.execute(
            text("SELECT count(*) FROM team_resource_grants WHERE resource_id = CAST(:id AS uuid)"), {"id": tid}
        ).scalar()
        settings_rows = pg_conn.execute(
            text("SELECT count(*) FROM resource_share_settings WHERE resource_id = CAST(:id AS uuid)"), {"id": tid}
        ).scalar()
        assert grants == 0 and settings_rows == 0


# ---------------------------------------------------------------------------
# 5. POST /api/update_tool_status
# ---------------------------------------------------------------------------
class TestUpdateToolStatusRoles:
    def test_owner_writes_status(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolStatus

        tool = _tool(pg_conn, status=True)
        body = {"id": str(tool["id"]), "status": False}
        assert _call(app, pg_conn, UpdateToolStatus, OWNER, json=body).status_code == 200
        assert _row(pg_conn, tool["id"])["status"] is False

    def test_grantee_writes_personal_preference(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolStatus

        tool = _tool(pg_conn, status=False)
        _share(pg_conn, tool["id"], "bob", "viewer")
        body = {"id": str(tool["id"]), "status": True}
        assert _call(app, pg_conn, UpdateToolStatus, "bob", json=body).status_code == 200
        assert _row(pg_conn, tool["id"])["status"] is False  # owner's switch untouched
        prefs = UserToolPreferencesRepository(pg_conn)
        assert prefs.in_chat_many("bob", [str(tool["id"])]) == {str(tool["id"]): True}

    def test_grantee_without_use_in_own_is_forbidden(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolStatus

        tool = _tool(pg_conn)
        _share(pg_conn, tool["id"], "bob", "viewer")
        set_settings(pg_conn, "tool", str(tool["id"]), {"viewers_can_use_in_agents": False}, OWNER)
        body = {"id": str(tool["id"]), "status": True}
        assert _call(app, pg_conn, UpdateToolStatus, "bob", json=body).status_code == 403
        assert _call(app, pg_conn, UpdateToolStatus, "nobody", json=body).status_code == 404


# ---------------------------------------------------------------------------
# 4. MCP save
# ---------------------------------------------------------------------------
def _mcp_tool(conn, url="https://mcp.example.com/mcp", secrets=None, auth_type="bearer"):
    cfg = {"server_url": url, "auth_type": auth_type, "transport_type": "http"}
    if secrets:
        cfg["encrypted_credentials"] = encrypt_credentials(secrets, OWNER)
    return UserToolsRepository(conn).create(
        OWNER, "mcp_tool", config=cfg, display_name="M", custom_name="M", description="",
        actions=[{"name": "old", "active": True}], status=True,
    )


def _stored_mcp_secret(conn, tool_id):
    """The secret a saved MCP tool runs with, and whose key it is under.

    A save moves the secret onto a connection of the tool's owner (see
    ``docsgpt/connectors``); a tool without one keeps it in its config.
    """
    from docsgpt.connectors import service
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    row = UserToolsRepository(conn).get_any(str(tool_id), OWNER)
    if not row.get("connection_id"):
        return decrypt_credentials(row["config"]["encrypted_credentials"], OWNER), OWNER
    assert "encrypted_credentials" not in row["config"]
    connection = ConnectorSessionsRepository(conn).get(str(row["connection_id"]))
    return service.get_credentials(connection), connection["user_id"]


def _mcp_connection_tool(conn, secrets, url="https://mcp.example.com/mcp"):
    """An MCP tool whose key lives on an owner's connection, as a save leaves it."""
    from docsgpt.connectors import catalog, service

    connection, _ = service.create_api_key_connection(
        conn, OWNER, catalog.get_definition("custom_mcp"), secrets,
        server_url=catalog.base_url(url), display_name="M",
    )
    return UserToolsRepository(conn).create(
        OWNER, "mcp_tool", config={"server_url": url, "auth_type": "bearer", "transport_type": "http"},
        display_name="M", custom_name="M", description="",
        actions=[{"name": "old", "active": True}], status=True, connection_id=str(connection["id"]),
    ), connection


class TestMCPSaveAccess:
    def _save(self, app, conn, user, body, discovered=None):
        from docsgpt.api.user.tools.mcp import MCPServerSave

        fake = MagicMock()
        fake.get_actions_metadata.return_value = discovered or [{"name": "t1"}]
        with patch("docsgpt.api.user.tools.mcp.MCPTool", return_value=fake) as cls:
            resp = _call(app, conn, MCPServerSave, user, json=body)
        return resp, cls

    def _count(self, conn):
        from sqlalchemy import text

        return conn.execute(text("SELECT count(*) FROM user_tools WHERE name = 'mcp_tool'")).scalar()

    def test_editor_updates_owner_row_no_duplicate(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "Renamed",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer",
                           "transport_type": "http"}}
        resp, cls = self._save(app, pg_conn, "ed", body)
        assert resp.status_code == 200, resp.json
        assert resp.json["id"] == str(tool["id"])
        assert self._count(pg_conn) == 1
        row = _row(pg_conn, tool["id"])
        assert row["display_name"] == "Renamed"
        # Stored creds were reused for discovery and kept, encrypted with the owner's key.
        assert cls.call_args.kwargs.get("user_id") == OWNER
        assert cls.call_args.kwargs["config"]["auth_credentials"] == {"bearer_token": "tok"}
        assert _stored_mcp_secret(pg_conn, tool["id"]) == ({"bearer_token": "tok"}, OWNER)

    def test_viewer_and_stranger_cannot_save_or_duplicate(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "vi", "viewer")
        body = {"id": str(tool["id"]), "displayName": "X",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer",
                           "transport_type": "http", "bearer_token": "new"}}
        assert self._save(app, pg_conn, "vi", body)[0].status_code == 403
        assert self._save(app, pg_conn, "nobody", body)[0].status_code == 404
        assert self._count(pg_conn) == 1

    def test_host_change_without_credentials_is_rejected(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://elsewhere.example.org/mcp", "auth_type": "bearer",
                           "transport_type": "http"}}
        resp, cls = self._save(app, pg_conn, OWNER, body)
        assert resp.status_code == 400
        assert resp.json["message"] == "Enter credentials for the new server"
        assert not cls.called
        assert _row(pg_conn, tool["id"])["config"]["server_url"] == "https://mcp.example.com/mcp"

    @pytest.mark.parametrize("url", ["http://mcp.example.com/mcp", "https://mcp.example.com:8443/mcp"])
    def test_scheme_or_port_change_without_credentials_is_rejected(self, app, pg_conn, url):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": url, "auth_type": "bearer", "transport_type": "http"}}
        resp, cls = self._save(app, pg_conn, "ed", body)
        assert resp.status_code == 400
        assert not cls.called
        assert _row(pg_conn, tool["id"])["config"]["server_url"] == "https://mcp.example.com/mcp"

    def test_host_change_with_new_credentials_replaces_them(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://elsewhere.example.org/mcp", "auth_type": "bearer",
                           "transport_type": "http", "bearer_token": "tok2"}}
        resp, _ = self._save(app, pg_conn, OWNER, body)
        assert resp.status_code == 200
        assert _row(pg_conn, tool["id"])["config"]["server_url"] == "https://elsewhere.example.org/mcp"
        assert _stored_mcp_secret(pg_conn, tool["id"]) == ({"bearer_token": "tok2"}, OWNER)

    def test_empty_secret_reuses_the_connections_key(self, app, pg_conn):
        tool, connection = _mcp_connection_tool(pg_conn, {"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "Renamed",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer",
                           "transport_type": "http"}}
        resp, cls = self._save(app, pg_conn, "ed", body)
        assert resp.status_code == 200, resp.json
        assert cls.call_args.kwargs["config"]["auth_credentials"] == {"bearer_token": "tok"}
        assert cls.call_args.kwargs["user_id"] == OWNER
        assert str(_row(pg_conn, tool["id"])["connection_id"]) == str(connection["id"])

    def test_editors_new_key_does_not_rotate_the_owners_connection(self, app, pg_conn):
        from docsgpt.connectors import service
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        tool, connection = _mcp_connection_tool(pg_conn, {"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer",
                           "transport_type": "http", "bearer_token": "tok2"}}
        resp, _ = self._save(app, pg_conn, "ed", body)
        assert resp.status_code == 200, resp.json
        assert _stored_mcp_secret(pg_conn, tool["id"]) == ({"bearer_token": "tok2"}, OWNER)
        # The owner's other tools on the old connection keep its key.
        old = ConnectorSessionsRepository(pg_conn).get(str(connection["id"]))
        assert service.get_credentials(old) == {"bearer_token": "tok"}

    def test_moved_server_does_not_inherit_the_connections_key(self, app, pg_conn):
        tool, _connection = _mcp_connection_tool(pg_conn, {"bearer_token": "tok"})
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://elsewhere.example.org/mcp", "auth_type": "bearer",
                           "transport_type": "http"}}
        resp, cls = self._save(app, pg_conn, OWNER, body)
        assert resp.status_code == 400
        assert not cls.called

    def test_editor_blocked_when_credentials_switch_off(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        set_settings(pg_conn, "tool", str(tool["id"]), {"editors_can_change_credentials": False}, OWNER)
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer",
                           "transport_type": "http"}}
        assert self._save(app, pg_conn, "ed", body)[0].status_code == 403

    def test_editor_oauth_reconnect_is_owner_only(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, auth_type="oauth")
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth",
                           "transport_type": "http", "oauth_task_id": "task-1"}}
        resp, _ = self._save(app, pg_conn, "ed", body)
        assert resp.status_code == 403

    def test_editor_oauth_save_without_reconnect_is_owner_only(self, app, pg_conn):
        # A shared OAuth server's connection is the owner's: an editor can't
        # save it, even with the same URL (the path, scopes or client could
        # still change while reusing the owner's tokens).
        tool = _mcp_tool(pg_conn, auth_type="oauth")
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "Renamed",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth",
                           "transport_type": "http"}}
        resp, _ = self._save(app, pg_conn, "ed", body)
        assert resp.status_code == 403
        assert _row(pg_conn, tool["id"])["display_name"] == "M"

    def test_editor_cannot_switch_oauth_server_to_other_auth(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, auth_type="oauth")
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer",
                           "transport_type": "http", "bearer_token": "mine"}}
        assert self._save(app, pg_conn, "ed", body)[0].status_code == 403
        assert _row(pg_conn, tool["id"])["config"]["auth_type"] == "oauth"

    def test_editor_cannot_switch_server_to_oauth(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "displayName": "M",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth",
                           "transport_type": "http"}}
        assert self._save(app, pg_conn, "ed", body)[0].status_code == 403

    def test_owner_oauth_save_needs_a_completed_sign_in(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, auth_type="oauth")
        body = {"id": str(tool["id"]), "displayName": "Renamed",
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth",
                           "transport_type": "http"}}
        resp, _ = self._save(app, pg_conn, OWNER, body)
        assert resp.status_code == 400
        assert _row(pg_conn, tool["id"])["display_name"] == "M"

    def test_auth_status_includes_team_mcp_tools(self, app, pg_conn):
        from docsgpt.api.user.tools.mcp import MCPAuthStatus

        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "vi", "viewer")
        resp = _call(app, pg_conn, MCPAuthStatus, "vi", method="get", path="/api/mcp_server/auth_status")
        assert resp.json["statuses"] == {str(tool["id"]): "configured"}


class TestMCPTestEndpointAccess:
    def _test(self, app, conn, user, body):
        from docsgpt.api.user.tools.mcp import TestMCPServerConfig

        fake = MagicMock()
        fake.test_connection.return_value = {"success": True, "tools_count": 1, "tools": []}
        with patch("docsgpt.api.user.tools.mcp.MCPTool", return_value=fake) as cls:
            resp = _call(app, conn, TestMCPServerConfig, user, json=body)
        return resp, cls

    def _body(self, tool, url="https://mcp.example.com/mcp", **extra):
        return {"id": str(tool["id"]), "config": {"server_url": url, "auth_type": "bearer",
                                                  "transport_type": "http", **extra}}

    def test_empty_secret_uses_stored_one_as_owner(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        resp, cls = self._test(app, pg_conn, "ed", self._body(tool))
        assert resp.status_code == 200 and resp.json["success"] is True
        assert cls.call_args.kwargs["config"]["auth_credentials"] == {"bearer_token": "tok"}
        assert cls.call_args.kwargs["user_id"] == OWNER

    def test_host_change_without_secret_is_400(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        resp, cls = self._test(app, pg_conn, OWNER, self._body(tool, url="https://new.example.org/mcp"))
        assert resp.status_code == 400
        assert resp.json["message"] == "Enter credentials for the new server"
        assert not cls.called
        resp, cls = self._test(app, pg_conn, OWNER, self._body(tool, url="https://new.example.org/mcp",
                                                                bearer_token="t2"))
        assert cls.call_args.kwargs["config"]["auth_credentials"] == {"bearer_token": "t2"}

    def test_scheme_downgrade_without_secret_is_400(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        resp, cls = self._test(app, pg_conn, "ed", self._body(tool, url="http://mcp.example.com/mcp"))
        assert resp.status_code == 400
        assert not cls.called

    def test_viewer_and_stranger_denied(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "vi", "viewer")
        assert self._test(app, pg_conn, "vi", self._body(tool))[0].status_code == 403
        assert self._test(app, pg_conn, "eve", self._body(tool))[0].status_code == 404

    def test_editor_test_of_stored_oauth_server_is_owner_only(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, auth_type="oauth")
        _share(pg_conn, tool["id"], "ed", "editor")
        resp, cls = self._test(app, pg_conn, "ed", self._body(tool, bearer_token="mine"))
        assert resp.status_code == 403 and not cls.called

    def test_editor_oauth_test_is_owner_only(self, app, pg_conn):
        tool = _mcp_tool(pg_conn, auth_type="oauth")
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]), "config": {"server_url": "https://mcp.example.com/mcp",
                                                  "auth_type": "oauth", "transport_type": "http"}}
        resp, cls = self._test(app, pg_conn, "ed", body)
        assert resp.status_code == 403 and not cls.called


# ---------------------------------------------------------------------------
# 6. Shared OAuth MCP servers: the connection is the owner's
# ---------------------------------------------------------------------------
class TestSharedOAuthMCPConfig:
    """``/api/update_tool`` and ``/api/update_tool_config`` can't move a shared
    OAuth server or switch a shared server to OAuth: OAuth tokens are looked up
    by owner + server URL, so either would run on the owner's sign-in
    elsewhere. Connection changes on OAuth servers are the owner's."""

    OTHER = {"server_url": "https://other-mcp.example.org/mcp", "auth_type": "oauth"}

    def _oauth_tool(self, conn):
        tool = _mcp_tool(conn, auth_type="oauth")
        _share(conn, tool["id"], "ed", "editor")
        return tool

    def test_update_tool_config_cannot_move_oauth_server(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolConfig

        tool = self._oauth_tool(pg_conn)
        body = {"id": str(tool["id"]), "config": dict(self.OTHER)}
        assert _call(app, pg_conn, UpdateToolConfig, "ed", json=body).status_code == 403
        assert _row(pg_conn, tool["id"])["config"]["server_url"] == "https://mcp.example.com/mcp"

    def test_update_tool_cannot_move_oauth_server(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        tool = self._oauth_tool(pg_conn)
        body = {"id": str(tool["id"]), "config": dict(self.OTHER)}
        assert _call(app, pg_conn, UpdateTool, "ed", json=body).status_code == 403
        assert _row(pg_conn, tool["id"])["config"]["server_url"] == "https://mcp.example.com/mcp"

    def test_update_tool_config_cannot_switch_server_to_oauth(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolConfig

        tool = _mcp_tool(pg_conn, secrets={"bearer_token": "tok"})
        _share(pg_conn, tool["id"], "ed", "editor")
        body = {"id": str(tool["id"]),
                "config": {"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth"}}
        assert _call(app, pg_conn, UpdateToolConfig, "ed", json=body).status_code == 403
        assert _row(pg_conn, tool["id"])["config"]["auth_type"] == "bearer"

    def test_editor_still_renames_oauth_server_without_config(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        tool = self._oauth_tool(pg_conn)
        body = {"id": str(tool["id"]), "customName": "Renamed"}
        assert _call(app, pg_conn, UpdateTool, "ed", json=body).status_code == 200
        assert _row(pg_conn, tool["id"])["custom_name"] == "Renamed"

    def test_owner_may_change_oauth_server_config(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateToolConfig

        tool = _mcp_tool(pg_conn, auth_type="oauth")
        body = {"id": str(tool["id"]), "config": dict(self.OTHER)}
        assert _call(app, pg_conn, UpdateToolConfig, OWNER, json=body).status_code == 200
        assert _row(pg_conn, tool["id"])["config"]["server_url"] == self.OTHER["server_url"]
