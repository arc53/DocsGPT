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
COINGECKO_MCP = "https://mcp.api.coingecko.com/mcp"
TWELVEDATA_MCP = "https://mcp.twelvedata.com/mcp"
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
            patch.multiple("docsgpt.connectors.mcp", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.api.user.tools.mcp", db_session=_yield, db_readonly=_yield):
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


def _keyless_connection(conn, connector_key: str = "mcp:coingecko") -> str:
    """A CoinGecko connection, as its Connect stores it through the no-auth MCP server form.

    ``connector_key="custom_mcp"`` is a connection made before Connect
    recorded the preset (or a no-auth custom server at CoinGecko's address).
    """
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "server_url) VALUES ('alice', 'custom_mcp', :k, 'none', 'connected', "
            "'mcp.api.coingecko.com', 'https://mcp.api.coingecko.com') RETURNING id"
        ),
        {"k": connector_key},
    ).scalar())


def _twelvedata_connection(conn) -> str:
    """A Twelve Data sign-in, as the preset's MCP OAuth flow stores it."""
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "server_url, encrypted_credentials) VALUES ('alice', 'mcp:https://mcp.twelvedata.com', "
            "'mcp:twelvedata', 'mcp_oauth', 'connected', 'Basic plan', 'https://mcp.twelvedata.com', :e) "
            "RETURNING id"
        ),
        {"e": encrypt_json({"tokens": {"access_token": "twelvedata-secret"}}, "alice")},
    ).scalar())


def _custom_connection(conn, base_url: str, auth_kind: str) -> str:
    """A custom MCP server at ``base_url``, added from the MCP server form rather than a preset's card.

    An OAuth server is keyed by its address (as one added before its preset
    existed is stored); a pasted key or no auth is a plain ``custom_mcp`` row.
    """
    provider = f"mcp:{base_url}" if auth_kind == "mcp_oauth" else "custom_mcp"
    secrets = {
        "mcp_oauth": {"tokens": {"access_token": "custom-secret"}},
        "api_key": {"credentials": {"api_key": "custom-key"}},
    }.get(auth_kind)
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "server_url, encrypted_credentials) VALUES ('alice', :p, 'custom_mcp', :a, 'connected', :l, :u, :e) "
            "RETURNING id"
        ),
        {"p": provider, "a": auth_kind, "l": base_url.split("://")[-1], "u": base_url,
         "e": encrypt_json(secrets, "alice") if secrets else None},
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

    @pytest.mark.parametrize("key, url", [
        ("mcp:coingecko", COINGECKO_MCP),
        ("mcp:drawio", "https://mcp.draw.io/mcp"),
    ])
    def test_keyless_presets_connect_without_oauth(self, key, url):
        config = service.connection_mcp_config(catalog.get_definition(key))
        assert config["server_url"] == url
        assert config["auth_type"] == "none"


class TestRecreate:
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

    def test_setup_rebuilds_a_keyless_preset_tool_without_oauth(self, app, pg_conn):
        cid = _keyless_connection(pg_conn)
        with _db(pg_conn), patch("docsgpt.agents.tools.mcp_tool.MCPTool.discover_tools"), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.get_actions_metadata",
                      side_effect=lambda: [dict(a) for a in ACTIONS]), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.__init__", return_value=None) as init, \
                patch.object(service, "mark_reconnect_needed") as flag:
            resp = _setup(app, cid)
        assert resp.status_code == 200, resp.get_json()
        flag.assert_not_called()
        discovery = init.call_args_list[0].args[0]
        assert discovery["server_url"] == COINGECKO_MCP
        assert discovery["auth_type"] == "none"
        assert discovery["connection_id"] == cid

        rows = _tools(pg_conn, cid)
        assert len(rows) == 1
        name, config, _, display_name, _, _ = rows[0]
        assert name == "mcp_tool"
        assert config["server_url"] == COINGECKO_MCP
        assert config["auth_type"] == "none"
        assert display_name == "CoinGecko"

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

    def test_setup_rebuilds_the_twelve_data_tool_from_its_sign_in(self, app, pg_conn):
        cid = _twelvedata_connection(pg_conn)
        actions = [{"name": "get_quote", "description": "Quote",
                    "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}}}]
        with _db(pg_conn), patch("docsgpt.agents.tools.mcp_tool.MCPTool.discover_tools") as discover, \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.get_actions_metadata",
                      side_effect=lambda: [dict(a) for a in actions]), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.__init__", return_value=None) as init:
            resp = _setup(app, cid)
        assert resp.status_code == 200, resp.get_json()
        assert discover.call_count == 1
        discovery = init.call_args_list[0].args[0]
        assert discovery["server_url"] == TWELVEDATA_MCP
        assert discovery["auth_type"] == "oauth"
        assert discovery["connection_id"] == cid
        assert "twelvedata-secret" not in str(discovery)

        [(name, config, saved, display_name, description, _)] = _tools(pg_conn, cid)
        assert name == "mcp_tool"
        assert config == {"server_url": TWELVEDATA_MCP, "auth_type": "oauth", "oauth_scopes": [],
                          "timeout": 30, "transport_type": "auto"}
        assert display_name == "Twelve Data"
        assert description == f"MCP Server: {TWELVEDATA_MCP}"
        assert [a["name"] for a in saved] == ["get_quote"]


CUSTOM_SERVERS_AT_PRESET_ADDRESSES = [
    pytest.param("https://mcp.twelvedata.com", "mcp_oauth", "mcp:twelvedata", id="twelvedata-oauth"),
    pytest.param("https://mcp.twelvedata.com", "api_key", "mcp:twelvedata", id="twelvedata-api-key"),
    pytest.param("https://mcp.alphavantage.co", "none", "mcp:alphavantage", id="alphavantage-key-in-url"),
]


class TestCustomServerAtAPresetAddress:
    """A custom server at a preset's address keeps its own path and sign-in.

    Its tool comes only from the MCP server form's save. Setup must not
    rebuild it from the preset's URL and auth, which would drop a custom path
    or pasted key, though the host still names it after the preset.
    """

    @pytest.mark.parametrize("base_url, auth_kind, preset", CUSTOM_SERVERS_AT_PRESET_ADDRESSES)
    def test_setup_does_not_rebuild_it_from_the_preset(self, app, pg_conn, base_url, auth_kind, preset):
        cid = _custom_connection(pg_conn, base_url, auth_kind)
        row = service.ConnectorSessionsRepository(pg_conn).get(cid)
        # Still the preset for admin switches and attribution.
        assert catalog.connector_key_for_row(row) == preset
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover",
                                 return_value=[dict(a) for a in ACTIONS]) as discover:
            resp = _setup(app, cid)
        assert resp.status_code == 200, resp.get_json()
        discover.assert_not_called()
        assert resp.get_json()["tools"] == []
        assert _tools(pg_conn, cid) == []

    @pytest.mark.parametrize("base_url, auth_kind, preset", CUSTOM_SERVERS_AT_PRESET_ADDRESSES)
    def test_no_preset_tool_even_when_actions_are_passed(self, pg_conn, base_url, auth_kind, preset):
        cid = _custom_connection(pg_conn, base_url, auth_kind)
        row = service.ConnectorSessionsRepository(pg_conn).get(cid)

        assert service.needs_mcp_discovery(pg_conn, row) is False
        assert service.ensure_connection_tools(pg_conn, "alice", row, mcp_actions=[dict(a) for a in ACTIONS]) == []
        assert _tools(pg_conn, cid) == []


def _row(connector_key: str, auth_kind: str, server_url: str = "", provider: str = "") -> dict:
    return {"connector_key": connector_key, "auth_kind": auth_kind, "server_url": server_url,
            "provider": provider or connector_key}


TWELVEDATA = "https://mcp.twelvedata.com"


class TestRebuildRule:
    """Setup rebuilds a preset's MCP tool only for a connection made through that preset."""

    @pytest.mark.parametrize("key, row, expected", [
        pytest.param("mcp:twelvedata", _row("mcp:twelvedata", "mcp_oauth"), True, id="preset-sign-in"),
        pytest.param("mcp:coingecko", _row("mcp:coingecko", "none"), True, id="keyless-preset-connect"),
        pytest.param("mcp:drawio", _row("mcp:drawio", "none"), True, id="keyless-preset-connect-drawio"),
        pytest.param("mcp:coingecko", _row("custom_mcp", "none"), False, id="custom-no-auth-at-keyless-preset"),
        pytest.param("mcp:drawio", _row("custom_mcp", "none"), False, id="custom-no-auth-at-keyless-preset-drawio"),
        pytest.param("mcp:twelvedata", _row("custom_mcp", "mcp_oauth"), False, id="custom-oauth"),
        pytest.param("mcp:twelvedata", _row("custom_mcp", "api_key"), False, id="custom-api-key"),
        pytest.param("mcp:alphavantage", _row("custom_mcp", "none"), False, id="custom-no-auth-at-oauth-preset"),
        pytest.param("mcp:coingecko", _row("custom_mcp", "api_key"), False, id="custom-api-key-at-keyless-preset"),
        pytest.param("github", _row("github", "oauth"), False, id="built-in-is-not-a-preset"),
        pytest.param("custom_mcp", _row("custom_mcp", "none"), False, id="custom-connector"),
    ])
    def test_rebuilds_from_preset(self, key, row, expected):
        assert service.rebuilds_from_preset(row, catalog.get_definition(key)) is expected

    def test_no_definition_is_not_a_preset(self):
        assert service.rebuilds_from_preset(_row("custom_mcp", "none"), None) is False

    def test_rebuild_config_is_the_preset_config_for_its_sign_in(self):
        row = _row("mcp:twelvedata", "mcp_oauth", TWELVEDATA, f"mcp:{TWELVEDATA}")
        assert service.connection_rebuild_config(row) == service.connection_mcp_config(
            catalog.get_definition("mcp:twelvedata")
        )

    def test_rebuild_config_is_none_for_a_custom_server_at_the_preset_address(self):
        row = _row("custom_mcp", "mcp_oauth", TWELVEDATA, f"mcp:{TWELVEDATA}")
        assert catalog.connector_key_for_row(row) == "mcp:twelvedata"
        assert service.connection_rebuild_config(row) is None

    def test_built_in_connectors_keep_their_own_config(self):
        github = catalog.get_definition("github")
        row = _row("github", "oauth")
        assert service.connection_rebuild_config(row) == service.builtin_mcp_config(github)
        assert service.connection_rebuild_config(row, writes=True) == service.builtin_mcp_config(github, writes=True)


class TestCustomServerFlag:
    """``custom_server`` tells the drawer setup cannot add the tool back."""

    @staticmethod
    def _detail(pg_conn, cid):
        return service.connection_detail(pg_conn, service.ConnectorSessionsRepository(pg_conn).get(cid))

    @pytest.mark.parametrize("base_url, auth_kind, preset", CUSTOM_SERVERS_AT_PRESET_ADDRESSES)
    def test_a_custom_server_at_a_preset_address_is_flagged(self, pg_conn, base_url, auth_kind, preset):
        detail = self._detail(pg_conn, _custom_connection(pg_conn, base_url, auth_kind))
        assert detail["connector_key"] == preset
        assert detail["custom_server"] is True

    def test_a_preset_sign_in_is_not_flagged(self, pg_conn):
        assert self._detail(pg_conn, _twelvedata_connection(pg_conn))["custom_server"] is False

    def test_a_keyless_preset_connect_is_not_flagged(self, pg_conn):
        assert self._detail(pg_conn, _keyless_connection(pg_conn))["custom_server"] is False

    def test_a_no_auth_custom_server_at_a_keyless_preset_address_is_flagged(self, pg_conn):
        detail = self._detail(pg_conn, _keyless_connection(pg_conn, connector_key="custom_mcp"))
        assert detail["connector_key"] == "mcp:coingecko"
        assert detail["custom_server"] is True

    def test_a_custom_server_elsewhere_is_not_flagged(self, pg_conn):
        detail = self._detail(pg_conn, _custom_connection(pg_conn, "https://mcp.example.com", "none"))
        assert detail["connector_key"] == "custom_mcp"
        assert detail["custom_server"] is False


DRAWIO_MCP = "https://mcp.draw.io/mcp"


def _save_no_auth(pg_conn, server_url: str, name: str = "My server") -> str:
    """The connection the MCP server form's save gives a no-auth server (what a keyless preset's Connect uses)."""
    from docsgpt.api.user.tools.mcp import _mcp_connection

    with _db(pg_conn):
        cid = _mcp_connection("alice", {"server_url": server_url}, "none", {}, name)
    assert cid is not None
    return cid


def _stored(pg_conn, cid) -> tuple:
    return tuple(pg_conn.execute(
        text("SELECT provider, connector_key, auth_kind FROM connector_sessions WHERE id = CAST(:c AS uuid)"),
        {"c": cid},
    ).one())


def _rows_at(pg_conn, base_url: str) -> int:
    return pg_conn.execute(
        text("SELECT count(*) FROM connector_sessions WHERE user_id = 'alice' AND server_url = :u"), {"u": base_url},
    ).scalar()


class TestKeylessPresetOrigin:
    """A no-auth save records a keyless preset only when its URL is the preset's own endpoint.

    CoinGecko's and draw.io's Connect save their ``mcp_url`` with no auth, the
    same form a no-auth custom server uses, and the connection keeps only the
    host. Recording the preset's key at save time is what lets setup tell the
    preset (rebuilt from its URL) from a custom path at its address (kept).
    """

    def test_connect_records_the_preset(self, pg_conn):
        cid = _save_no_auth(pg_conn, COINGECKO_MCP, "CoinGecko")
        assert _stored(pg_conn, cid) == ("custom_mcp", "mcp:coingecko", "none")

    @pytest.mark.parametrize("url", [
        pytest.param("https://mcp.api.coingecko.com/sse", id="other-path"),
        pytest.param(f"{COINGECKO_MCP}?apikey=x", id="query"),
        pytest.param(TWELVEDATA_MCP, id="oauth-preset-saved-without-auth"),
    ])
    def test_any_other_endpoint_stays_custom(self, pg_conn, url):
        cid = _save_no_auth(pg_conn, url)
        assert _stored(pg_conn, cid) == ("custom_mcp", "custom_mcp", "none")

    def test_connect_upgrades_a_connection_made_before_it_recorded_the_preset(self, pg_conn):
        legacy = _keyless_connection(pg_conn, connector_key="custom_mcp")
        cid = _save_no_auth(pg_conn, COINGECKO_MCP, "CoinGecko")
        assert cid == legacy
        assert _stored(pg_conn, cid) == ("custom_mcp", "mcp:coingecko", "none")
        assert _rows_at(pg_conn, "https://mcp.api.coingecko.com") == 1

    def test_a_custom_path_never_downgrades_the_preset_connection(self, pg_conn):
        """The account index gives one row per host: the preset's tool lives on it too."""
        preset = _keyless_connection(pg_conn)
        cid = _save_no_auth(pg_conn, "https://mcp.api.coingecko.com/sse")
        assert cid == preset
        assert _stored(pg_conn, cid) == ("custom_mcp", "mcp:coingecko", "none")

    @pytest.mark.parametrize("url", [
        pytest.param("https://mcp.api.coingecko.com/sse", id="coingecko"),
        pytest.param(DRAWIO_MCP.rstrip("/") + "/sse", id="drawio"),
    ])
    def test_a_no_auth_custom_server_at_a_keyless_preset_address_is_not_rebuilt(self, app, pg_conn, url):
        cid = _save_no_auth(pg_conn, url)
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover",
                                 return_value=[dict(a) for a in ACTIONS]) as discover:
            resp = _setup(app, cid)
        assert resp.status_code == 200, resp.get_json()
        discover.assert_not_called()
        assert resp.get_json()["tools"] == []
        assert _tools(pg_conn, cid) == []
        row = service.ConnectorSessionsRepository(pg_conn).get(cid)
        assert row is not None
        assert service.connection_detail(pg_conn, row)["custom_server"] is True

    def test_the_preset_connect_is_rebuilt_from_its_own_endpoint(self, app, pg_conn):
        cid = _save_no_auth(pg_conn, COINGECKO_MCP, "CoinGecko")
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover",
                                 return_value=[dict(a) for a in ACTIONS]) as discover:
            resp = _setup(app, cid)
        assert resp.status_code == 200, resp.get_json()
        discover.assert_called_once()
        assert discover.call_args.args[2]["config"]["server_url"] == COINGECKO_MCP
        assert discover.call_args.args[2]["config"]["auth_type"] == "none"
        [(name, config, *_)] = _tools(pg_conn, cid)
        assert name == "mcp_tool"
        assert config["server_url"] == COINGECKO_MCP
        assert config["auth_type"] == "none"
        row = service.ConnectorSessionsRepository(pg_conn).get(cid)
        assert row is not None
        assert service.connection_detail(pg_conn, row)["custom_server"] is False

    def test_a_connection_made_before_is_rebuilt_once_connect_records_the_preset(self, app, pg_conn):
        cid = _keyless_connection(pg_conn, connector_key="custom_mcp")
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover",
                                 return_value=[dict(a) for a in ACTIONS]) as discover:
            before = _setup(app, cid)
            assert before.get_json()["tools"] == []
            discover.assert_not_called()

        assert _save_no_auth(pg_conn, COINGECKO_MCP, "CoinGecko") == cid
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover",
                                 return_value=[dict(a) for a in ACTIONS]) as discover:
            after = _setup(app, cid)
        discover.assert_called_once()
        assert [t["name"] for t in after.get_json()["tools"]] == ["mcp_tool"]
