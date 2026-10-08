"""Adding back an MCP preset's tool (Notion, Linear…) after it was deleted from Tools."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
from docsgpt.agents.tools.mcp_tool import MCPReauthorizationRequired
from docsgpt.connectors import catalog, service
from docsgpt.security.encryption import encrypt_json

NOTION_MCP = "https://mcp.notion.com/mcp"
ACTIONS = [
    {"name": "notion-search", "description": "Search", "annotations": {"readOnlyHint": True},
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "notion-create-pages", "description": "Create pages", "annotations": {"readOnlyHint": False},
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}}}},
]


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.connector.connections", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.mcp", db_session=_yield, db_readonly=_yield):
        yield


def _call(app, resource, method, path, user="alice", body=None, args=()):
    with app.test_request_context(path, method=method.upper(), json=body):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return getattr(resource(), method)(*args)


def _connection(conn, status="connected") -> str:
    """A Notion sign-in, as the MCP OAuth flow stores it."""
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "server_url, encrypted_credentials) VALUES ('alice', 'mcp:https://mcp.notion.com', 'mcp:notion', "
            "'mcp_oauth', :s, 'Acme workspace', 'https://mcp.notion.com', :e) RETURNING id"
        ),
        {"s": status, "e": encrypt_json({"tokens": {"access_token": "notion-secret"}}, "alice")},
    ).scalar())


def _tools(conn, cid):
    return conn.execute(text(
        "SELECT name, config, actions, display_name, description, connection_id FROM user_tools "
        "WHERE connection_id = CAST(:c AS uuid)"
    ), {"c": cid}).all()


def _setup(app, cid):
    from docsgpt.api.connector.connections import ConnectionSetup

    return _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                 body={"create_tools": True}, args=[cid])


class TestPresetConfig:
    def test_excalidraw_recreation_keeps_authentication_disabled(self):
        definition = catalog.get_definition("mcp:excalidraw")
        assert service.connection_mcp_config(definition) == {
            "server_url": "https://mcp.excalidraw.com/mcp", "auth_type": "none",
            "timeout": 30, "transport_type": "auto",
        }

    def test_is_the_config_the_sign_in_saves(self):
        definition = catalog.get_definition("mcp:notion")
        assert service.connection_mcp_config(definition) == {
            "server_url": NOTION_MCP, "auth_type": "oauth", "oauth_scopes": [],
            "timeout": 30, "transport_type": "auto",
        }

    def test_built_in_connectors_keep_their_own(self):
        github = catalog.get_definition("github")
        assert service.connection_mcp_config(github) == service.builtin_mcp_config(github)
        assert service.connection_mcp_config(catalog.get_definition("telegram")) is None
        assert service.connection_mcp_config(catalog.get_definition("custom_mcp")) is None
        # The built-in-only helpers still ignore presets.
        assert service.builtin_mcp_config(catalog.get_definition("mcp:notion")) is None


class TestRecreate:
    def test_setup_rebuilds_excalidraw_without_oauth(self, app, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        row = ConnectorSessionsRepository(pg_conn).create(
            "alice", "custom_mcp", connector_key="custom_mcp", auth_kind="none",
            display_name="Excalidraw", account_label="mcp.excalidraw.com",
            server_url="https://mcp.excalidraw.com",
        )
        cid = str(row["id"])
        actions = [{"name": "export_to_excalidraw", "description": "Export diagram"}]
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover", return_value=actions) as discover:
            for _ in range(2):
                resp = _setup(app, cid)
                assert resp.status_code == 200, resp.get_json()
        discover.assert_called_once()
        assert discover.call_args.args[2]["config"]["auth_type"] == "none"
        tools = _tools(pg_conn, cid)
        assert len(tools) == 1
        assert tools[0].config["auth_type"] == "none"
        assert "oauth_scopes" not in tools[0].config
        assert tools[0].display_name == "Excalidraw"

    def test_setup_rebuilds_the_deleted_tool_from_the_sign_in(self, app, pg_conn):
        cid = _connection(pg_conn)
        with _db(pg_conn), patch("docsgpt.agents.tools.mcp_tool.MCPTool.discover_tools") as discover, \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.get_actions_metadata",
                      side_effect=lambda: [dict(a) for a in ACTIONS]), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.__init__", return_value=None) as init:
            for _ in range(2):
                resp = _setup(app, cid)
        assert resp.status_code == 200, resp.get_json()
        # Discovered once, with the stored sign-in: the connection's id, never its tokens.
        assert discover.call_count == 1
        # The first MCPTool is the discovery one (the tool registry builds more).
        discovery = init.call_args_list[0].args[0]
        assert discovery["server_url"] == NOTION_MCP
        assert discovery["auth_type"] == "oauth"
        assert discovery["connection_id"] == cid
        assert discovery["query_mode"] is True
        assert "notion-secret" not in str(discovery)

        rows = _tools(pg_conn, cid)
        assert len(rows) == 1
        name, config, actions, display_name, description, connection_id = rows[0]
        assert name == "mcp_tool"
        assert str(connection_id) == cid
        assert config == {"server_url": NOTION_MCP, "auth_type": "oauth", "oauth_scopes": [],
                          "timeout": 30, "transport_type": "auto"}
        assert "notion-secret" not in str(config)
        assert display_name == "Notion"
        assert description == f"MCP Server: {NOTION_MCP}"
        by_name = {a["name"]: a for a in actions}
        # Reads Allow, writes Ask first, as after a fresh sign-in.
        assert by_name["notion-search"]["access"] == "read"
        assert not by_name["notion-search"].get("require_approval")
        assert by_name["notion-create-pages"]["access"] == "write"
        assert by_name["notion-create-pages"]["require_approval"] is True
        assert by_name["notion-search"]["parameters"]["properties"]["query"]["filled_by_llm"] is True
        assert [t["name"] for t in resp.get_json()["tools"]] == ["mcp_tool"]

    def test_a_connection_that_still_has_its_tool_is_not_rescanned(self, app, pg_conn):
        cid = _connection(pg_conn)
        pg_conn.execute(text(
            "INSERT INTO user_tools (user_id, name, config, connection_id) VALUES ('alice', 'mcp_tool', "
            "'{\"server_url\": \"https://mcp.notion.com/mcp\", \"auth_type\": \"oauth\"}'::jsonb, CAST(:c AS uuid))"
        ), {"c": cid})
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover") as discover:
            resp = _setup(app, cid)
        assert resp.status_code == 200
        discover.assert_not_called()
        assert len(_tools(pg_conn, cid)) == 1

    def test_unreachable_server_creates_nothing_and_keeps_the_connection(self, app, pg_conn):
        cid = _connection(pg_conn)
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover", side_effect=RuntimeError("down")), \
                patch.object(service, "mark_reconnect_needed") as flag:
            resp = _setup(app, cid)
        assert resp.status_code == 502
        assert resp.get_json()["code"] == "tools_unavailable"
        assert _tools(pg_conn, cid) == []
        flag.assert_not_called()
        status = pg_conn.execute(text(
            "SELECT status FROM connector_sessions WHERE id = CAST(:c AS uuid)"
        ), {"c": cid}).scalar()
        assert status == "connected"

    def test_rejected_sign_in_asks_to_reconnect(self, app, pg_conn):
        cid = _connection(pg_conn)
        expired = RuntimeError("Failed to discover tools")
        expired.__cause__ = MCPReauthorizationRequired("OAuth session expired")
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover", side_effect=expired), \
                patch.object(service, "mark_reconnect_needed") as flag:
            resp = _setup(app, cid)
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "reconnect"
        assert _tools(pg_conn, cid) == []
        flag.assert_called_once()
        assert flag.call_args.args[0] == cid

    def test_signed_out_connection_must_reconnect_first(self, app, pg_conn):
        cid = _connection(pg_conn, status="reconnect_needed")
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover") as discover:
            resp = _setup(app, cid)
        assert resp.status_code == 409
        discover.assert_not_called()

    def test_preset_turned_off_by_an_admin_is_not_rebuilt(self, app, pg_conn):
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        cid = _connection(pg_conn)
        ConnectorPoliciesRepository(pg_conn).upsert("mcp:notion", enabled=False)
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover") as discover:
            resp = _setup(app, cid)
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "disabled"
        discover.assert_not_called()
        assert _tools(pg_conn, cid) == []
