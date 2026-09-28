"""Auth, ownership and failure paths of the connections API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docsgpt.connectors import service
from tests.connectors.test_connections_api import _call, _connection, _db, app  # noqa: F401  (fixture)

_CID = "00000000-0000-0000-0000-000000000001"


def _resources():
    from docsgpt.api.connector import connections as c

    return [
        (c.ConnectorCatalog, "get", ()),
        (c.ConnectionsList, "get", ()),
        (c.ConnectionsList, "post", ()),
        (c.ConnectionDetail, "get", (_CID,)),
        (c.ConnectionDetail, "delete", (_CID,)),
        (c.ConnectionDisconnect, "post", (_CID,)),
        (c.ConnectionSetup, "post", (_CID,)),
        (c.ConnectionReconnect, "post", (_CID,)),
        (c.ConnectionPickerToken, "post", (_CID,)),
        (c.ConnectionClaim, "post", ()),
        (c.ConnectionToolPermissions, "put", (_CID, "t1")),
        (c.ConnectionRefreshTools, "post", (_CID,)),
        (c.ToolCredentialMode, "put", ("t1",)),
    ]


@pytest.mark.parametrize("index", range(13))
def test_every_endpoint_needs_a_signed_in_user(app, index):  # noqa: F811
    resource, method, args = _resources()[index]
    resp = _call(app, resource, method, "/api/connections", user=None, body={}, args=args)
    assert resp.status_code == 401


@pytest.mark.parametrize("index", [3, 4, 5, 6, 7, 8, 11])
def test_someone_elses_connection_is_not_found(app, pg_conn, index):  # noqa: F811
    resource, method, _ = _resources()[index]
    cid = _connection(pg_conn, user="victim", secrets={"credentials": {"token": "t"}})
    with _db(pg_conn):
        resp = _call(app, resource, method, f"/api/connections/{cid}", body={"credentials": {"token": "x"}},
                     args=(cid,))
    assert resp.status_code == 404


class TestCreateErrors:
    def test_oauth_connector_does_not_take_pasted_keys(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "google_drive", "credentials": {"token": "x"}})
        assert resp.status_code == 400

    def test_credentials_must_be_an_object(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "telegram", "credentials": "123:abc"})
        assert resp.status_code == 400

    def test_disabled_connector_is_forbidden(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionsList
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        ConnectorPoliciesRepository(pg_conn).upsert("telegram", enabled=False)
        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "telegram", "credentials": {"token": "123456:ABCDEFG"}})
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "disabled"

    def test_missing_field_is_a_bad_request(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "telegram", "credentials": {}})
        assert resp.status_code == 400


class TestToolPermissions:
    def _tool(self, pg_conn, cid):
        from sqlalchemy import text

        return str(pg_conn.execute(text(
            "INSERT INTO user_tools (user_id, name, config, connection_id, actions) VALUES ('alice', 'telegram', "
            "'{}'::jsonb, CAST(:c AS uuid), '[{\"name\": \"telegram_send_message\", \"active\": true}]'::jsonb) "
            "RETURNING id"
        ), {"c": cid}).scalar())

    def test_sets_permissions_on_the_connection_tool(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionToolPermissions

        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        tool_id = self._tool(pg_conn, cid)
        with _db(pg_conn):
            resp = _call(app, ConnectionToolPermissions, "put", "/p",
                         body={"permissions": {"telegram_send_message": "off"}}, args=(cid, tool_id))
        assert resp.status_code == 200
        action = resp.get_json()["tool"]["actions"][0]
        assert action["permission"] == "off"

    def test_unknown_permission_is_rejected(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionToolPermissions

        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        with _db(pg_conn):
            resp = _call(app, ConnectionToolPermissions, "put", "/p",
                         body={"permissions": {"telegram_send_message": "sometimes"}}, args=(cid, "t1"))
        assert resp.status_code == 400

    def test_tool_of_another_connection_is_not_found(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionToolPermissions

        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        other = _connection(pg_conn, account_label="…zzzz", secrets={"credentials": {"token": "u"}})
        tool_id = self._tool(pg_conn, other)
        with _db(pg_conn):
            resp = _call(app, ConnectionToolPermissions, "put", "/p",
                         body={"permissions": {"telegram_send_message": "off"}}, args=(cid, tool_id))
        assert resp.status_code == 404


class TestRefreshTools:
    def test_returns_the_diff(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionRefreshTools

        cid = _connection(pg_conn, provider="mcp:https://m.example.com", auth_kind="mcp_oauth", secrets={})
        with _db(pg_conn), patch("docsgpt.connectors.mcp.refresh_mcp_tools",
                                 return_value={"added": ["a"], "removed": [], "tools": []}):
            resp = _call(app, ConnectionRefreshTools, "post", "/r", args=(cid,))
        assert resp.status_code == 200
        assert resp.get_json()["added"] == ["a"]

    def test_signed_out_server_asks_to_reconnect(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionRefreshTools

        cid = _connection(pg_conn, provider="mcp:https://m.example.com", auth_kind="mcp_oauth", secrets={})
        with _db(pg_conn), patch("docsgpt.connectors.mcp.refresh_mcp_tools",
                                 side_effect=service.ConnectionUnavailable("gone")):
            resp = _call(app, ConnectionRefreshTools, "post", "/r", args=(cid,))
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "reconnect"

    def test_server_failure_is_a_bad_gateway(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionRefreshTools

        cid = _connection(pg_conn, provider="mcp:https://m.example.com", auth_kind="mcp_oauth", secrets={})
        with _db(pg_conn), patch("docsgpt.connectors.mcp.refresh_mcp_tools", side_effect=RuntimeError("boom")):
            resp = _call(app, ConnectionRefreshTools, "post", "/r", args=(cid,))
        assert resp.status_code == 502


class TestPickerToken:
    def test_signed_out_connection_asks_to_reconnect(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionPickerToken

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={})
        with _db(pg_conn), patch.object(service, "picker_token", side_effect=service.ConnectionUnavailable("x")):
            resp = _call(app, ConnectionPickerToken, "post", "/p", args=(cid,))
        assert resp.status_code == 409

    def test_provider_outage_is_retryable(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionPickerToken

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={})
        with _db(pg_conn), patch.object(service, "picker_token",
                                        side_effect=service.TransientConnectionError("x")):
            resp = _call(app, ConnectionPickerToken, "post", "/p", args=(cid,))
        assert resp.status_code == 503

    def test_api_key_connection_has_no_picker(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionPickerToken

        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        with _db(pg_conn):
            resp = _call(app, ConnectionPickerToken, "post", "/p", args=(cid,))
        assert resp.status_code == 404


class TestClaim:
    def test_needs_provider_and_token(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionClaim

        with _db(pg_conn):
            resp = _call(app, ConnectionClaim, "post", "/c", body={"provider": "google_drive"})
        assert resp.status_code == 400

    def test_unknown_token_is_not_found(self, app, pg_conn):  # noqa: F811
        from docsgpt.api.connector.connections import ConnectionClaim

        with _db(pg_conn):
            resp = _call(app, ConnectionClaim, "post", "/c",
                         body={"provider": "google_drive", "session_token": "nope"})
        assert resp.status_code == 404
