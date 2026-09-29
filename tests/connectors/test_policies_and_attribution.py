"""Admin connector policies, sharing modes and connector attribution."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.connectors import catalog, service
from docsgpt.security.encryption import encrypt_json


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    modules = (
        "docsgpt.connectors.service",
        "docsgpt.connectors.resolve",
        "docsgpt.connectors.attribution",
        "docsgpt.api.connector.connections",
        "docsgpt.api.admin.connectors",
        "docsgpt.api.user.tools.mcp",
    )
    patches = []
    for module in modules:
        for name in ("db_session", "db_readonly"):
            target = f"{module}.{name}"
            try:
                patches.append(patch(target, _yield))
                patches[-1].start()
            except AttributeError:
                patches.pop()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


def _connection(conn, user="alice", provider="telegram", status="connected", auth_kind="api_key",
                server_url=None, secrets=None) -> str:
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "server_url, encrypted_credentials) VALUES (:u, :p, :p, :a, :s, :l, :url, :e) RETURNING id"
        ),
        {"u": user, "p": provider, "a": auth_kind, "s": status, "l": f"{user}@example.com", "url": server_url,
         "e": encrypt_json(secrets or {"credentials": {"token": "tok"}}, user)},
    ).scalar())


def _call(app, resource, method, path, *, user="alice", body=None, roles=None, args=()):
    with app.test_request_context(path, method=method.upper(), json=body):
        from flask import request

        request.decoded_token = {"sub": user, "roles": roles or ["user"]} if user else None
        return getattr(resource(), method)(*args)


class TestPresets:
    def test_presets_are_in_the_catalog(self):
        presets = [d for d in catalog.all_definitions() if d.publisher == "preset"]
        assert {p.key for p in presets} >= {"mcp:notion", "mcp:linear"}
        for preset in presets:
            assert preset.mcp_url.startswith("https://")
            assert preset.auth_kind in ("mcp_oauth", "none")
            assert preset.tool_templates == ("mcp_tool",)

    def test_existing_mcp_connection_maps_to_its_preset(self):
        row = {"provider": "mcp:https://mcp.linear.app", "server_url": "https://mcp.linear.app",
               "connector_key": "custom_mcp"}
        assert catalog.connector_key_for_row(row) == "mcp:linear"


class TestAdminPolicies:
    def test_requires_admin(self, app, pg_conn):
        from docsgpt.api.admin.connectors import AdminConnectorsResource

        with _db(pg_conn):
            resp = _call(app, AdminConnectorsResource, "get", "/api/admin/connectors")
        assert resp.status_code == 403

    def test_lists_setup_state_without_values(self, app, pg_conn, monkeypatch):
        from docsgpt.api.admin.connectors import AdminConnectorsResource
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "secret-client-id")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", None)
        _connection(pg_conn, provider="google_drive", auth_kind="oauth")
        with _db(pg_conn):
            resp = _call(app, AdminConnectorsResource, "get", "/api/admin/connectors", roles=["admin"])
        payload = resp.get_json()
        drive = next(c for c in payload["connectors"] if c["key"] == "google_drive")
        assert drive["required_settings"] == [
            {"name": "GOOGLE_CLIENT_ID", "set": True}, {"name": "GOOGLE_CLIENT_SECRET", "set": False},
        ]
        assert drive["connection_count"] == 1
        # Sync-only: the page shows no sharing policy for it.
        assert drive["capabilities"] == ["sync"]
        assert "secret-client-id" not in json.dumps(payload)
        assert payload["allow_custom_mcp"] is True

    def test_github_is_ready_and_lists_its_optional_app_settings(self, app, pg_conn, monkeypatch):
        """Tokens need no setup; the GitHub App settings only add Sign in with GitHub."""
        from docsgpt.api.admin.connectors import AdminConnectorsResource
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "Iv1.secret-client")
        monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", None)
        monkeypatch.setattr(settings, "GITHUB_APP_SLUG", None)
        with _db(pg_conn):
            resp = _call(app, AdminConnectorsResource, "get", "/api/admin/connectors", roles=["admin"])
        payload = resp.get_json()
        github = next(c for c in payload["connectors"] if c["key"] == "github")
        assert github["configured"] is True and github["enabled"] is True
        assert github["required_settings"] == []
        assert github["oauth_settings"] == [
            {"name": "GITHUB_CLIENT_ID", "set": True},
            {"name": "GITHUB_CLIENT_SECRET", "set": False},
            {"name": "GITHUB_APP_SLUG", "set": False},
        ]
        assert github["oauth_configured"] is False
        assert "Iv1.secret-client" not in json.dumps(payload)
        drive = next(c for c in payload["connectors"] if c["key"] == "google_drive")
        assert drive["oauth_settings"] == [] and drive["oauth_configured"] is False

    def test_disable_connector_and_custom_mcp(self, app, pg_conn):
        from docsgpt.api.admin.connectors import AdminConnectorsResource

        with _db(pg_conn):
            resp = _call(app, AdminConnectorsResource, "put", "/api/admin/connectors", roles=["admin"], body={
                "policies": {"telegram": {"enabled": False, "credential_mode": "member"}},
                "allow_custom_mcp": False,
            })
            assert resp.status_code == 200
            entries = {e["key"]: e for e in service.catalog_for_user(pg_conn, "bob", is_admin=False)}
            assert "telegram" not in entries
            assert "custom_mcp" not in entries
            with pytest.raises(service.ConnectorDisabled):
                service.create_api_key_connection(
                    pg_conn, "bob", catalog.get_definition("telegram"), {"token": "long-enough-token"},
                )

    def test_a_preset_server_on_a_key_follows_the_preset_switch(self, app, pg_conn):
        """A key-based connection to a preset's server is that preset, not a
        custom server: turning custom servers off leaves it alone, and turning
        the preset off stops it."""
        from docsgpt.api.admin.connectors import AdminConnectorsResource

        linear = catalog.get_definition("mcp:linear")
        custom = catalog.get_definition("custom_mcp")
        with _db(pg_conn):
            _call(app, AdminConnectorsResource, "put", "/api/admin/connectors", roles=["admin"], body={
                "policies": {}, "allow_custom_mcp": False,
            })
            row, _ = service.create_api_key_connection(
                pg_conn, "bob", custom, {"api_key": "lin-key-123456"}, server_url=linear.mcp_base_url,
            )
            assert catalog.connector_key_for_row(row) == "mcp:linear"
            with pytest.raises(service.ConnectorDisabled):
                service.create_api_key_connection(
                    pg_conn, "bob", custom, {"api_key": "other-key-123456"}, server_url="https://mcp.example.com",
                )
            _call(app, AdminConnectorsResource, "put", "/api/admin/connectors", roles=["admin"], body={
                "policies": {"mcp:linear": {"enabled": False}}, "allow_custom_mcp": True,
            })
            with pytest.raises(service.ConnectorDisabled):
                service.create_api_key_connection(
                    pg_conn, "bob", custom, {"api_key": "lin-key-654321"}, server_url=linear.mcp_base_url,
                )

    def test_unconfigured_connectors_are_off_until_an_admin_turns_them_on(self, app, pg_conn, monkeypatch):
        from docsgpt.api.admin.connectors import AdminConnectorsResource
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", None)
        with _db(pg_conn):
            before = _call(app, AdminConnectorsResource, "get", "/api/admin/connectors", roles=["admin"]).get_json()
            # Changing only the sharing mode must not switch it on.
            _call(app, AdminConnectorsResource, "put", "/api/admin/connectors", roles=["admin"],
                  body={"policies": {"share_point": {"credential_mode": "member"}}})
            middle = _call(app, AdminConnectorsResource, "get", "/api/admin/connectors", roles=["admin"]).get_json()
            _call(app, AdminConnectorsResource, "put", "/api/admin/connectors", roles=["admin"],
                  body={"policies": {"share_point": {"enabled": True}}})
            after = _call(app, AdminConnectorsResource, "get", "/api/admin/connectors", roles=["admin"]).get_json()

        def enabled(payload, key):
            return next(c for c in payload["connectors"] if c["key"] == key)["enabled"]

        assert enabled(before, "share_point") is False
        assert enabled(before, "telegram") is True
        assert enabled(middle, "share_point") is False
        assert enabled(after, "share_point") is True

    def test_rejects_unknown_connector(self, app, pg_conn):
        from docsgpt.api.admin.connectors import AdminConnectorsResource

        with _db(pg_conn):
            resp = _call(app, AdminConnectorsResource, "put", "/api/admin/connectors", roles=["admin"],
                         body={"policies": {"nope": {"enabled": False}}})
        assert resp.status_code == 400

    def test_custom_mcp_switch_is_enforced_server_side(self, app, pg_conn):
        from docsgpt.api.user.tools.mcp import TestMCPServerConfig
        from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository

        AppMetadataRepository(pg_conn).set("connectors.allow_custom_mcp", "false")
        with _db(pg_conn), patch("docsgpt.api.user.tools.mcp._validate_mcp_server_url"):
            custom = _call(app, TestMCPServerConfig, "post", "/api/mcp_server/test",
                           body={"config": {"server_url": "https://tools.example.com/mcp"}})
        assert custom.status_code == 403

    def test_disabled_connector_stops_existing_tools(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        cid = _connection(pg_conn)
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", enabled=False)
        with _db(pg_conn):
            resolved = resolve_connection({"connection_id": cid, "user_id": "alice"}, "alice")
        assert resolved.available is False

    def test_forced_member_mode_overrides_the_share(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        owner = _connection(pg_conn)
        bobs = _connection(pg_conn, user="bob")
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", credential_mode="member")
        with _db(pg_conn):
            resolved = resolve_connection(
                {"connection_id": owner, "user_id": "alice", "credential_mode": "owner"}, "bob",
            )
        assert resolved.connection_id == bobs


class TestCredentialMode:
    def _tool(self, conn, cid, user="alice"):
        return str(conn.execute(
            text("INSERT INTO user_tools (user_id, name, connection_id) VALUES (:u, 'telegram', CAST(:c AS uuid)) "
                 "RETURNING id"),
            {"u": user, "c": cid},
        ).scalar())

    def test_owner_sets_member_mode(self, app, pg_conn):
        from docsgpt.api.connector.connections import ToolCredentialMode

        tool = self._tool(pg_conn, _connection(pg_conn))
        with _db(pg_conn):
            resp = _call(app, ToolCredentialMode, "put", "/x", body={"mode": "member"}, args=[tool])
        assert resp.status_code == 200
        mode = pg_conn.execute(text("SELECT credential_mode FROM user_tools WHERE id = CAST(:i AS uuid)"),
                               {"i": tool}).scalar()
        assert mode == "member"

    def test_other_users_cannot(self, app, pg_conn):
        from docsgpt.api.connector.connections import ToolCredentialMode

        tool = self._tool(pg_conn, _connection(pg_conn))
        with _db(pg_conn):
            resp = _call(app, ToolCredentialMode, "put", "/x", user="bob", body={"mode": "member"}, args=[tool])
        assert resp.status_code == 404

    def test_forced_policy_wins(self, app, pg_conn):
        from docsgpt.api.connector.connections import ToolCredentialMode
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        tool = self._tool(pg_conn, _connection(pg_conn))
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", credential_mode="owner")
        with _db(pg_conn):
            resp = _call(app, ToolCredentialMode, "put", "/x", body={"mode": "member"}, args=[tool])
        assert resp.status_code == 409
        assert resp.get_json()["mode"] == "owner"


def _executor(user):
    from docsgpt.agents.tool_executor import ToolExecutor

    return ToolExecutor(user=user)


def _pause(executor, tool, action_name):
    with patch("docsgpt.agents.tool_executor.ToolActionParser") as parser:
        parser.return_value.parse_args.return_value = ("t1", action_name, {})
        return executor.check_pause(
            {"t1": tool}, SimpleNamespace(id="c1", name=action_name, thought_signature=None), "OpenAILLM",
        )


class TestSharedWrites:
    def _tool(self, cid):
        return {
            "id": "tool-1",
            "user_id": "alice",
            "name": "postgres",
            "config": {},
            "connection_id": cid,
            "credential_mode": "owner",
            "actions": [
                {"name": "postgres_execute_sql", "access": "write", "require_approval": False, "active": True},
                {"name": "postgres_get_schema", "access": "read", "require_approval": False, "active": True},
            ],
        }

    def test_member_on_owners_account_must_approve_writes(self, pg_conn):
        cid = _connection(pg_conn, provider="postgres")
        with _db(pg_conn):
            pause = _pause(_executor("bob"), self._tool(cid), "postgres_execute_sql")
        assert pause["pause_type"] == "awaiting_approval"

    def test_member_reads_are_not_gated(self, pg_conn):
        cid = _connection(pg_conn, provider="postgres")
        with _db(pg_conn):
            assert _pause(_executor("bob"), self._tool(cid), "postgres_get_schema") is None

    def test_owner_keeps_their_own_choice(self, pg_conn):
        cid = _connection(pg_conn, provider="postgres")
        with _db(pg_conn):
            assert _pause(_executor("alice"), self._tool(cid), "postgres_execute_sql") is None


class TestAttribution:
    def test_tool_call_events_name_the_connector_not_the_account(self, pg_conn):
        cid = _connection(pg_conn, provider="mcp:https://mcp.notion.com", auth_kind="mcp_oauth",
                          server_url="https://mcp.notion.com", secrets={"tokens": {"access_token": "t"}})
        # MCP rows are stored as custom_mcp and named after their preset.
        pg_conn.execute(text("UPDATE connector_sessions SET connector_key = 'custom_mcp' WHERE id = CAST(:i AS uuid)"),
                        {"i": cid})
        executor = _executor("alice")
        tool = {
            "id": "tool-1", "user_id": "alice", "name": "mcp_tool", "connection_id": cid,
            "config": {"server_url": "https://mcp.notion.com/mcp", "auth_type": "oauth"},
            "actions": [{"name": "search", "active": True, "parameters": {"properties": {}},
                         "annotations": {"readOnlyHint": True}}],
        }
        fake_tool = SimpleNamespace(execute_action=lambda *a, **k: "ok", config={})
        call = SimpleNamespace(id="c1", name="search", arguments="{}", thought_signature=None)
        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolActionParser") as parser, patch.object(
            type(executor), "_get_or_load_tool", return_value=fake_tool
        ), patch("docsgpt.agents.tool_executor._record_proposed", return_value=True), patch(
            "docsgpt.agents.tool_executor._mark_executed"
        ):
            parser.return_value.parse_args.return_value = ("t1", "search", {})
            events = list(executor._execute({"t1": tool}, call, "OpenAILLM"))
        final = events[-1]["data"]
        assert final["connector_key"] == "mcp:notion"
        assert final["connector_name"] == "Notion"
        assert final["access"] == "read"
        assert "alice@example.com" not in json.dumps(events)

    def test_built_in_tools_carry_no_connector(self):
        executor = _executor("alice")
        assert executor._resolve_connection({"id": "x", "name": "memory"}) is None

    def test_citations_name_the_connector(self, pg_conn):
        from docsgpt.connectors.attribution import connector_labels

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth")
        source = str(pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, connection_id) VALUES ('alice', 'Handbook', CAST(:c AS uuid)) "
            "RETURNING id"
        ), {"c": cid}).scalar())
        upload = str(pg_conn.execute(text(
            "INSERT INTO sources (user_id, name) VALUES ('alice', 'Upload') RETURNING id"
        )).scalar())
        with _db(pg_conn):
            labels = connector_labels([source, upload, "not-a-uuid"])
        assert labels == {source: {"connector_key": "google_drive", "connector_name": "Google Drive"}}

    def test_classic_retriever_stamps_connector(self, pg_conn):
        from docsgpt.retriever.classic_rag import ClassicRAG

        retriever = ClassicRAG.__new__(ClassicRAG)
        with patch("docsgpt.connectors.attribution.connector_labels",
                   return_value={"s1": {"connector_key": "google_drive", "connector_name": "Google Drive"}}) as lookup:
            first = retriever._connector_labels.for_source("s1")
            again = retriever._connector_labels.for_source("s1")
        assert first == again == {"connector_key": "google_drive", "connector_name": "Google Drive"}
        assert lookup.call_count == 1
