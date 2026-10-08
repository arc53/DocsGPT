"""Tests for re-reading an MCP connection's actions."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
import docsgpt.agents.tools.mcp_tool  # noqa: F401,E402  (patched below)
from docsgpt.connectors import mcp, service
from docsgpt.security.encryption import encrypt_json


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.connectors.mcp", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield):
        yield


def _connection(conn, *, auth_kind="mcp_oauth", status="connected", secrets=None) -> dict:
    row = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "server_url, encrypted_credentials) VALUES ('alice', 'mcp:https://mcp.linear.app', 'mcp:linear', :a, "
            ":s, 'alice@example.com', 'https://mcp.linear.app', :e) RETURNING *"
        ),
        {"a": auth_kind, "s": status, "e": encrypt_json(secrets or {}, "alice")},
    ).one()
    return dict(row._mapping)


def _tool(conn, connection_id, actions) -> str:
    return str(conn.execute(
        text(
            "INSERT INTO user_tools (user_id, name, config, actions, connection_id) VALUES ('alice', 'mcp_tool', "
            "CAST(:c AS jsonb), CAST(:a AS jsonb), CAST(:cid AS uuid)) RETURNING id"
        ),
        {"c": json.dumps({"server_url": "https://mcp.linear.app/mcp", "auth_type": "oauth"}),
         "a": json.dumps(actions), "cid": str(connection_id)},
    ).scalar())


def _action(name, **extra):
    return {"name": name, "description": name, "parameters": {"properties": {"q": {"type": "string"}}}, **extra}


class TestRefresh:
    def test_keeps_choices_adds_new_actions_and_drops_removed_ones(self, pg_conn):
        connection = _connection(pg_conn)
        tool_id = _tool(pg_conn, connection["id"], [
            _action("list_issues", active=False, require_approval=True),
            _action("archived_action"),
        ])
        discovered = [
            _action("list_issues", annotations={"readOnlyHint": True}),
            _action("create_issue", annotations={"readOnlyHint": False}),
        ]
        with _db(pg_conn), patch.object(mcp, "_discover", return_value=discovered):
            result = mcp.refresh_mcp_tools("alice", connection)
        assert result["added"] == ["create_issue"]
        assert result["removed"] == ["archived_action"]
        actions = {a["name"]: a for a in pg_conn.execute(
            text("SELECT actions FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": tool_id}
        ).scalar()}
        assert set(actions) == {"list_issues", "create_issue"}
        # The user's choices survive a refresh.
        assert actions["list_issues"]["active"] is False
        assert actions["list_issues"]["require_approval"] is True
        # New writes default to needing approval.
        assert actions["create_issue"]["access"] == "write"
        assert actions["create_issue"]["require_approval"] is True
        assert actions["create_issue"]["parameters"]["properties"]["q"]["filled_by_llm"] is True
        assert [t["id"] for t in result["tools"]] == [tool_id]

    def test_fixed_values_survive_for_parameters_that_still_exist(self, pg_conn):
        connection = _connection(pg_conn)
        pinned = _action("search_issues")
        pinned["parameters"]["properties"] = {
            "q": {"type": "string", "filled_by_llm": True, "value": ""},
            "team": {"type": "string", "filled_by_llm": False, "value": "ENG"},
            "gone": {"type": "string", "filled_by_llm": False, "value": "x"},
        }
        tool_id = _tool(pg_conn, connection["id"], [pinned])
        fresh = _action("search_issues")
        fresh["parameters"]["properties"] = {"q": {"type": "string"}, "team": {"type": "string"}}
        with _db(pg_conn), patch.object(mcp, "_discover", return_value=[fresh]):
            mcp.refresh_mcp_tools("alice", connection)
        action = pg_conn.execute(
            text("SELECT actions FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": tool_id}
        ).scalar()[0]
        properties = action["parameters"]["properties"]
        assert properties["team"] == {"type": "string", "filled_by_llm": False, "value": "ENG"}
        assert properties["q"]["filled_by_llm"] is True
        assert "gone" not in properties

    def test_other_tools_on_the_connection_are_left_alone(self, pg_conn):
        connection = _connection(pg_conn)
        pg_conn.execute(
            text("INSERT INTO user_tools (user_id, name, config, connection_id) VALUES ('alice', 'telegram', "
                 "'{}'::jsonb, CAST(:c AS uuid))"),
            {"c": str(connection["id"])},
        )
        with _db(pg_conn), patch.object(mcp, "_discover") as discover:
            result = mcp.refresh_mcp_tools("alice", connection)
        discover.assert_not_called()
        assert result == {"added": [], "removed": [], "tools": []}


class TestDiscover:
    def test_oauth_connection_passes_its_id_not_tokens(self):
        connection = {"id": "c1", "auth_kind": "mcp_oauth", "status": "connected"}
        tool = {"config": {"server_url": "https://mcp.linear.app/mcp", "encrypted_credentials": "v1-blob"}}
        fake = MagicMock()
        fake.get_actions_metadata.return_value = [_action("search")]
        with patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=fake) as tool_cls:
            assert mcp._discover("alice", connection, tool) == [_action("search")]
        config = tool_cls.call_args.args[0]
        assert config["connection_id"] == "c1"
        assert config["query_mode"] is True
        assert "encrypted_credentials" not in config
        fake.discover_tools.assert_called_once()

    def test_api_key_connection_supplies_its_credentials(self):
        connection = {"id": "c1", "auth_kind": "api_key", "status": "connected"}
        with patch.object(service, "get_credentials", return_value={"bearer_token": "tok"}), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool") as tool_cls:
            mcp._discover("alice", connection, {"config": {"server_url": "https://m.example.com/mcp"}})
        assert tool_cls.call_args.args[0]["auth_credentials"] == {"bearer_token": "tok"}

    def test_signed_out_oauth_connection_must_reconnect(self):
        connection = {"id": "c1", "auth_kind": "mcp_oauth", "status": "reconnect_needed"}
        with pytest.raises(service.ConnectionUnavailable), patch("docsgpt.agents.tools.mcp_tool.MCPTool") as tool_cls:
            mcp._discover("alice", connection, {"config": {}})
        tool_cls.assert_not_called()


def test_oauth_resource_is_the_full_mcp_endpoint():
    """Linear and Sentry publish ``https://host/mcp`` as their protected
    resource; the SDK must be given that endpoint, not only the origin."""
    from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url

    from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

    oauth = DocsGPTOAuth(
        mcp_url="https://mcp.linear.app/mcp",
        redis_client=MagicMock(),
        redirect_uri="https://example.com/callback",
        user_id="user1",
    )
    assert oauth.context.server_url == "https://mcp.linear.app/mcp"
    requested = resource_url_from_server_url(oauth.context.server_url)
    # Servers that publish the endpoint, and those that publish the origin.
    assert check_resource_allowed(requested_resource=requested, configured_resource="https://mcp.linear.app/mcp")
    assert check_resource_allowed(requested_resource=requested, configured_resource="https://mcp.linear.app")
    # Stored tokens stay keyed by the server's origin.
    assert oauth.context.storage.server_url == "https://mcp.linear.app"


def test_callback_hands_the_sdk_an_authorization_result():
    """The MCP SDK reads ``.code``, ``.state`` and the RFC 9207 ``.iss`` off the
    callback's result; Linear advertises ``iss`` and refuses a sign-in without it."""
    import asyncio

    from mcp.shared.auth import AuthorizationCodeResult

    from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

    stored = {
        "mcp_oauth:code:st": b"the-code",
        "mcp_oauth:iss:st": b"https://mcp.linear.app",
    }
    redis_client = MagicMock()
    redis_client.get.side_effect = stored.get
    oauth = DocsGPTOAuth(
        mcp_url="https://mcp.linear.app/mcp",
        redis_client=redis_client,
        redirect_uri="https://example.com/callback",
        user_id="user1",
    )
    oauth.extracted_state = "st"

    result = asyncio.run(oauth.callback_handler())

    assert isinstance(result, AuthorizationCodeResult)
    assert (result.code, result.state, result.iss) == ("the-code", "st", "https://mcp.linear.app")
    redis_client.delete.assert_any_call("mcp_oauth:iss:st")


@pytest.mark.parametrize(
    "method, basic, body_client_id",
    [("client_secret_basic", True, False), ("client_secret_post", False, True), ("none", False, True)],
)
def test_token_request_uses_one_client_authentication(method, basic, body_client_id):
    """Linear registers clients for ``client_secret_basic`` and refuses a token
    request that also names the client in the body; RFC 6749 wants one method."""
    from mcp.shared.auth import OAuthClientInformationFull

    from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

    oauth = DocsGPTOAuth(
        mcp_url="https://mcp.linear.app/mcp",
        redis_client=MagicMock(),
        redirect_uri="https://example.com/callback",
        user_id="user1",
    )
    oauth.context.client_info = OAuthClientInformationFull(
        client_id="cid",
        client_secret=None if method == "none" else "secret",
        token_endpoint_auth_method=method,
        redirect_uris=["https://example.com/callback"],
    )

    data, headers = oauth.context.prepare_token_auth(
        {"grant_type": "authorization_code", "code": "c", "client_id": "cid"},
        {"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert headers.get("Authorization", "").startswith("Basic ") is basic
    assert ("client_id" in data) is body_client_id
    assert data["code"] == "c"


# api.supabase.com's registration response, as the SDK parses it: a secret is
# issued, but no token-endpoint auth method is named.
_REGISTRATION_WITHOUT_A_METHOD = {
    "client_id": "18ab2f17-c343-4061-bcce-5faf309a94ae",
    "client_secret": "the-registered-secret",
    "client_secret_expires_at": 0,
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "redirect_uris": ["https://example.com/callback"],
    "token_endpoint_auth_method": None,
}


def _oauth_for(pg_conn, client_info):
    """A DocsGPTOAuth whose stored registration is ``client_info``."""
    import asyncio

    from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

    connection = _connection(pg_conn, secrets={"client_info": client_info})
    oauth = DocsGPTOAuth(
        mcp_url="https://mcp.linear.app/mcp",
        redis_client=MagicMock(),
        redirect_uri="https://example.com/callback",
        user_id="alice",
        connection_id=connection["id"],
    )
    with _db(pg_conn):
        oauth.context.client_info = asyncio.run(oauth.context.storage.get_client_info())
    return oauth


class TestDefaultTokenEndpointAuthMethod:
    def test_a_secret_without_a_named_method_authenticates_the_token_request(self, pg_conn):
        """Supabase issues a ``client_secret`` and names no auth method.

        Read as a public client, the token request carried no credentials at
        all and Supabase answered ``422 {"message":"Required parameter:
        client_secret"}`` — only after the user had already signed in. RFC 7591
        §2 makes ``client_secret_basic`` the default whenever the method is
        omitted, which is the form ``prepare_token_auth`` applies for a secret.
        """
        oauth = _oauth_for(pg_conn, _REGISTRATION_WITHOUT_A_METHOD)

        assert oauth.context.client_info.token_endpoint_auth_method == "client_secret_basic"

        data, headers = oauth.context.prepare_token_auth(
            {"grant_type": "authorization_code", "code": "the-code", "client_id": "18ab2f17"},
            {"Content-Type": "application/x-www-form-urlencoded"},
        )

        # The secret reaches the server, and by one method only (RFC 6749 §2.3).
        assert headers["Authorization"].startswith("Basic ")
        assert "client_secret" not in data
        assert "client_id" not in data
        assert data["code"] == "the-code"

    def test_a_named_method_is_left_alone(self, pg_conn):
        """A registration that names its method keeps it — no clobbering."""
        stored = dict(_REGISTRATION_WITHOUT_A_METHOD, token_endpoint_auth_method="client_secret_post")
        oauth = _oauth_for(pg_conn, stored)

        assert oauth.context.client_info.token_endpoint_auth_method == "client_secret_post"

        data, headers = oauth.context.prepare_token_auth({"grant_type": "authorization_code"}, {})
        assert "Authorization" not in headers
        assert data["client_secret"] == "the-registered-secret"

    def test_a_public_client_stays_unauthenticated(self, pg_conn):
        """A server that issues no secret registered a public client; the
        default must not invent credentials for it."""
        stored = dict(_REGISTRATION_WITHOUT_A_METHOD, client_secret=None)
        oauth = _oauth_for(pg_conn, stored)

        assert oauth.context.client_info.token_endpoint_auth_method is None

        data, headers = oauth.context.prepare_token_auth({"grant_type": "authorization_code"}, {})
        assert "Authorization" not in headers
        assert "client_secret" not in data

