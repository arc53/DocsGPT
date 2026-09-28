"""Tests for the read side of the connection service and its API."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.connectors import service


def _session(conn, user="alice", provider="google_drive", **cols) -> str:
    cols = {"status": "authorized", "user_email": f"{user}@example.com", **cols}
    casts = {"token_info": "jsonb", "session_data": "jsonb"}
    names = ", ".join(["user_id", "provider", *cols])
    values = ", ".join(
        [":user_id", ":provider", *[f"CAST(:{k} AS {casts[k]})" if k in casts else f":{k}" for k in cols]]
    )
    return str(
        conn.execute(
            text(f"INSERT INTO connector_sessions ({names}) VALUES ({values}) RETURNING id"),
            {"user_id": user, "provider": provider, **cols},
        ).scalar()
    )


def _source(conn, connection_id, user="alice", name="Handbook") -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id) "
                "VALUES (:u, :n, 'connector:file', 'weekly', CAST(:c AS uuid)) RETURNING id"
            ),
            {"u": user, "n": name, "c": connection_id},
        ).scalar()
    )


def _tool(conn, connection_id, user="alice") -> str:
    actions = [
        {"name": "search_pages", "description": "Search", "active": True},
        {"name": "create_page", "description": "Create", "active": True, "require_approval": True},
    ]
    return str(
        conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, display_name, actions, connection_id) "
                "VALUES (:u, 'mcp_tool', 'Notion', CAST(:a AS jsonb), CAST(:c AS uuid)) RETURNING id"
            ),
            {"u": user, "a": json.dumps(actions), "c": connection_id},
        ).scalar()
    )


class TestNormalizeStatus:
    @pytest.mark.parametrize(
        "row,expected",
        [
            ({"status": "authorized"}, "connected"),
            ({"status": "reconnect_needed"}, "reconnect_needed"),
            ({"status": "pending"}, "pending"),
            ({"status": "pending", "token_info": {"access_token": "x"}}, "connected"),
            ({"status": None, "session_data": {"tokens": {"access_token": "x"}}}, "connected"),
            ({"status": None, "session_data": {"client_info": {}}}, "pending"),
            ({"status": None, "encrypted_credentials": "v2:..."}, "connected"),
        ],
    )
    def test_statuses(self, row, expected):
        assert service.normalize_status(row) == expected

    def test_worst_status(self):
        assert service.worst_status(["connected", "reconnect_needed"]) == "reconnect_needed"
        assert service.worst_status([]) is None


class TestListing:
    def test_lists_finished_connections_with_counts(self, pg_conn):
        drive = _session(pg_conn)
        _session(pg_conn, provider="confluence", status="pending", user_email=None)
        _source(pg_conn, drive)
        _source(pg_conn, drive, name="Wiki")
        connections = service.list_connections(pg_conn, "alice")
        assert [c["connector_key"] for c in connections] == ["google_drive"]
        only = connections[0]
        assert only["name"] == "Google Drive"
        assert only["account_label"] == "alice@example.com"
        assert only["status"] == "connected"
        assert only["source_count"] == 2
        assert "token_info" not in only and "session_token" not in only

    def test_other_users_rows_hidden(self, pg_conn):
        _session(pg_conn, user="bob")
        assert service.list_connections(pg_conn, "alice") == []

    def test_detail_lists_sources_and_tools(self, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        drive = _session(pg_conn, status="reconnect_needed")
        _source(pg_conn, drive)
        _tool(pg_conn, drive)
        row = ConnectorSessionsRepository(pg_conn).get(drive)
        detail = service.connection_detail(pg_conn, row)
        assert detail["sources"][0]["sync_state"] == "paused_reconnect"
        actions = {a["name"]: a for a in detail["tools"][0]["actions"]}
        assert actions["search_pages"] == {
            "name": "search_pages", "description": "Search", "access": "read", "permission": "always",
        }
        assert actions["create_page"]["access"] == "write"
        assert actions["create_page"]["permission"] == "ask"


class TestCatalogForUser:
    def test_states(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
        monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", None)
        _session(pg_conn)
        _session(pg_conn, provider="confluence", status="reconnect_needed")
        entries = {e["key"]: e for e in service.catalog_for_user(pg_conn, "alice", is_admin=False)}
        assert entries["google_drive"]["state"] == "connected"
        assert entries["google_drive"]["connected_count"] == 1
        assert entries["confluence"]["state"] == "reconnect"
        assert entries["share_point"]["state"] == "needs_setup"
        assert entries["share_point"]["missing_settings"] == []
        assert entries["telegram"]["state"] == "available"
        assert entries["custom_mcp"]["state"] == "custom"

    def test_admin_sees_missing_setting_names(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", None)
        entries = {e["key"]: e for e in service.catalog_for_user(pg_conn, "alice", is_admin=True)}
        assert "MICROSOFT_CLIENT_ID" in entries["share_point"]["missing_settings"]

    def test_policy_disables(self, pg_conn):
        entries = {
            e["key"]: e
            for e in service.catalog_for_user(
                pg_conn, "alice", is_admin=False, policies={"telegram": {"enabled": False}}
            )
        }
        assert entries["telegram"]["state"] == "disabled"
        assert entries["telegram"]["available"] is False


@contextmanager
def _patched_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.connector.connections.db_readonly", _yield):
        yield


@pytest.fixture
def app():
    return Flask(__name__)


def _call(app, resource, path, token, *args):
    with app.test_request_context(path):
        from flask import request

        request.decoded_token = token
        return resource().get(*args)


class TestRoutes:
    def test_catalog_requires_auth(self, app):
        from docsgpt.api.connector.connections import ConnectorCatalog

        assert _call(app, ConnectorCatalog, "/api/connectors/catalog", None).status_code == 401

    def test_catalog(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectorCatalog

        with _patched_db(pg_conn):
            resp = _call(app, ConnectorCatalog, "/api/connectors/catalog", {"sub": "alice"})
        assert resp.status_code == 200
        keys = {c["key"] for c in resp.get_json()["connectors"]}
        assert "telegram" in keys

    def test_list_and_detail(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail, ConnectionsList

        drive = _session(pg_conn)
        with _patched_db(pg_conn):
            listed = _call(app, ConnectionsList, "/api/connections", {"sub": "alice"})
            detail = _call(app, ConnectionDetail, f"/api/connections/{drive}", {"sub": "alice"}, drive)
        assert listed.get_json()["connections"][0]["id"] == drive
        assert detail.get_json()["connection"]["id"] == drive

    def test_detail_of_another_users_connection_is_404(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail

        drive = _session(pg_conn, user="bob")
        with _patched_db(pg_conn):
            resp = _call(app, ConnectionDetail, f"/api/connections/{drive}", {"sub": "alice"}, drive)
        assert resp.status_code == 404

    def test_detail_of_bad_id_is_404(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail

        with _patched_db(pg_conn):
            resp = _call(app, ConnectionDetail, "/api/connections/nope", {"sub": "alice"}, "nope")
        assert resp.status_code == 404


class TestDisconnect:
    def test_clears_credentials_keeps_resources(self, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        drive = _session(
            pg_conn, session_token="tok", token_info=json.dumps({"access_token": "at", "refresh_token": "rt"}),
        )
        source = _source(pg_conn, drive)
        repo = ConnectorSessionsRepository(pg_conn)
        result = service.disconnect(pg_conn, repo.get(drive))
        assert result["status"] == "disconnected"
        row = repo.get(drive)
        assert row["token_info"] is None and row["session_token"] is None
        linked = pg_conn.execute(
            text("SELECT connection_id FROM sources WHERE id = CAST(:id AS uuid)"), {"id": source}
        ).scalar()
        assert str(linked) == drive

    def test_mcp_keeps_client_registration(self, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        mcp = _session(
            pg_conn,
            provider="mcp:https://mcp.example.com",
            status=None,
            session_data=json.dumps({"tokens": {"access_token": "x"}, "client_info": {"client_id": "c"}}),
        )
        repo = ConnectorSessionsRepository(pg_conn)
        service.disconnect(pg_conn, repo.get(mcp))
        assert repo.get(mcp)["session_data"] == {"client_info": {"client_id": "c"}}

    def test_route_rejects_other_users(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDisconnect

        drive = _session(pg_conn, user="bob")

        @contextmanager
        def _yield():
            yield pg_conn

        with patch("docsgpt.api.connector.connections.db_session", _yield), app.test_request_context(
            f"/api/connections/{drive}/disconnect", method="POST"
        ):
            from flask import request

            request.decoded_token = {"sub": "alice"}
            resp = ConnectionDisconnect().post(drive)
        assert resp.status_code == 404
