"""The built-in GitHub connector: two sign-ins, repository sync and read-only MCP tools."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.connectors import catalog, service
from docsgpt.security.encryption import encrypt_json

READONLY_MCP = "https://api.githubcopilot.com/mcp/readonly"


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def app_settings(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "Iv1.client")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "app-secret")
    monkeypatch.setattr(settings, "GITHUB_APP_SLUG", "docsgpt-acme")


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.connector.connections", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.mcp", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.resolve", db_readonly=_yield), \
            patch.multiple("docsgpt.api.connector.routes", db_session=_yield, db_readonly=_yield):
        yield


def _call(app, resource, method, path, user="alice", body=None, args=(), query=None):
    with app.test_request_context(path, method=method.upper(), json=body, query_string=query):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return getattr(resource(), method)(*args)


def _connection(conn, user="alice", auth_kind="api_key", secrets=None, status="connected", label="octocat") -> str:
    secrets = secrets if secrets is not None else {"credentials": {"access_token": "github_pat_alice"}}
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "encrypted_credentials) VALUES (:u, 'github', 'github', :a, :s, :l, :e) RETURNING id"
        ),
        {"u": user, "a": auth_kind, "s": status, "l": label, "e": encrypt_json(secrets, user)},
    ).scalar())


def _response(payload, status=200, headers=None):
    response = MagicMock(status_code=status, headers=headers or {})
    response.json.return_value = payload
    response.ok = status < 400
    return response


class TestCatalog:
    def test_github_syncs_and_reads_with_a_token_and_no_admin_setup(self, monkeypatch):
        from docsgpt.core.settings import settings

        for name in ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GITHUB_APP_SLUG"):
            monkeypatch.setattr(settings, name, None)
        definition = catalog.get_definition("github")
        assert definition.configured
        assert definition.capabilities == ("sync", "read")
        assert definition.sync_ingestor == "github"
        assert definition.mcp_url == READONLY_MCP
        assert definition.setup == {"tools": "ask", "sync": "ask"}
        payload = definition.to_dict()
        assert payload["sign_in_methods"] == ["api_key"]
        assert [f["key"] for f in payload["credential_fields"]] == ["access_token"]

    def test_github_app_sign_in_is_offered_once_configured(self, app_settings):
        assert catalog.get_definition("github").to_dict()["sign_in_methods"] == ["oauth", "api_key"]

    def test_other_connectors_have_one_sign_in(self):
        assert catalog.get_definition("google_drive").to_dict()["sign_in_methods"] == ["oauth"]
        assert catalog.get_definition("s3").to_dict()["sign_in_methods"] == ["api_key"]

    def test_generic_mcp_tools_do_not_belong_to_github(self):
        """Every MCP tool would otherwise be listed as GitHub's."""
        assert catalog.definition_for_tool("mcp_tool") is None
        assert "mcp_tool" not in catalog.tool_connector_keys()


class TestTokenSignIn:
    def test_token_is_checked_and_named_after_the_account(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn), patch("docsgpt.connectors.github.requests.get",
                                 return_value=_response({"login": "octocat"})) as get:
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "github", "credentials": {"access_token": "github_pat_abc"}})
        assert resp.status_code == 201
        assert resp.get_json()["connection"]["account_label"] == "octocat"
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer github_pat_abc"
        assert resp.get_json()["setup"] == {"tools": "ask", "sync": "ask"}

    def test_rejected_token_is_not_stored(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn), patch("docsgpt.connectors.github.requests.get",
                                 return_value=_response({"message": "Bad credentials"}, 401)):
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "github", "credentials": {"access_token": "nope"}})
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "invalid_credentials"
        assert pg_conn.execute(text("SELECT count(*) FROM connector_sessions")).scalar() == 0


class TestAppSignIn:
    def test_callback_stores_the_app_token_under_the_login(self, app, pg_conn, app_settings):
        import base64
        import json

        from docsgpt.api.connector.routes import ConnectorsCallback, build_authorization

        with _db(pg_conn), patch("docsgpt.api.connector.routes.service.ensure_can_store_credentials"):
            started = build_authorization("github", "alice")
        assert started["authorization_url"].startswith("https://github.com/login/oauth/authorize?")
        state = started["state"]
        token_info = {
            "access_token": "ghu_a", "refresh_token": "ghr_r", "expiry": "2099-01-01T00:00:00+00:00",
            "user_info": {"login": "octocat", "name": "Octo"},
        }
        with _db(pg_conn), patch("docsgpt.parser.connectors.github.auth.GitHubAuth.exchange_code_for_tokens",
                                 return_value=token_info):
            with app.test_request_context(f"/api/connectors/callback?code=c&state={state}"):
                page = ConnectorsCallback().get()
        assert page.status_code == 200
        assert b"github_auth_success" in page.data
        row = pg_conn.execute(text("SELECT * FROM connector_sessions WHERE provider = 'github'")).one()._mapping
        assert row["account_label"] == "octocat" and row["auth_kind"] == "oauth"
        assert service.read_secrets(dict(row))["token_info"]["refresh_token"] == "ghr_r"
        assert json.loads(base64.urlsafe_b64decode(state))["provider"] == "github"

    def test_installation_link_carries_the_same_state(self, pg_conn, app_settings):
        from docsgpt.api.connector.routes import build_authorization

        cid = _connection(pg_conn, auth_kind="oauth", secrets={"token_info": {"access_token": "ghu"}})
        with _db(pg_conn), patch("docsgpt.api.connector.routes.service.ensure_can_store_credentials"):
            started = build_authorization("github", "alice", cid, install=True)
        assert started["authorization_url"].startswith(
            "https://github.com/apps/docsgpt-acme/installations/new?state="
        )

    def test_installation_redirect_without_state_is_a_friendly_page(self, app, app_settings):
        """Installing the app from GitHub itself lands on the callback with no state."""
        from docsgpt.api.connector.routes import ConnectorsCallback

        with app.test_request_context("/api/connectors/callback?code=c&installation_id=9&setup_action=install"):
            page = ConnectorsCallback().get()
        assert page.status_code == 200
        assert b"installed" in page.data.lower()

    def test_expired_app_token_is_refreshed_before_use(self, pg_conn, app_settings):
        cid = _connection(pg_conn, auth_kind="oauth", secrets={"token_info": {
            "access_token": "ghu_old", "refresh_token": "ghr_r", "expiry": "2000-01-01T00:00:00+00:00",
        }})
        row = pg_conn.execute(text("SELECT * FROM connector_sessions WHERE id = CAST(:c AS uuid)"),
                              {"c": cid}).one()._mapping
        with _db(pg_conn), patch(
            "docsgpt.parser.connectors.github.auth.GitHubAuth.refresh_access_token",
            return_value={"access_token": "ghu_new", "refresh_token": "ghr_next", "expiry": "2099-01-01T00:00:00+00:00"},
        ):
            assert service.access_credentials(dict(row)) == {"access_token": "ghu_new"}


class TestRepositories:
    def test_token_lists_the_repositories_it_can_read(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionRepositories

        cid = _connection(pg_conn)
        page = [
            {"full_name": "octocat/private", "name": "private", "owner": {"login": "octocat"}, "private": True,
             "description": "Secret", "default_branch": "main", "pushed_at": "2026-09-01T00:00:00Z",
             "html_url": "https://github.com/octocat/private"},
        ]
        with _db(pg_conn), patch("docsgpt.connectors.github.requests.get", return_value=_response(page)) as get:
            resp = _call(app, ConnectionRepositories, "get", f"/api/connections/{cid}/repositories", args=[cid])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["repositories"] == [{
            "full_name": "octocat/private", "private": True, "description": "Secret",
            "default_branch": "main", "updated_at": "2026-09-01T00:00:00Z",
            "html_url": "https://github.com/octocat/private",
        }]
        assert data["install_url"] is None
        assert get.call_args.args[0] == "https://api.github.com/user/repos"
        assert "github_pat" not in resp.get_data(as_text=True)

    def test_app_sign_in_lists_the_installations_repositories(self, app, pg_conn, app_settings):
        from docsgpt.api.connector.connections import ConnectionRepositories

        cid = _connection(pg_conn, auth_kind="oauth", secrets={"token_info": {
            "access_token": "ghu_a", "expiry": "2099-01-01T00:00:00+00:00"}})

        def fake_get(url, **kwargs):
            if url.endswith("/user/installations"):
                return _response({"installations": [{"id": 7}]})
            assert url.endswith("/user/installations/7/repositories")
            return _response({"repositories": [{"full_name": "acme/api", "private": True}]})

        with _db(pg_conn), patch("docsgpt.connectors.github.requests.get", side_effect=fake_get):
            resp = _call(app, ConnectionRepositories, "get", f"/api/connections/{cid}/repositories", args=[cid])
        data = resp.get_json()
        assert [r["full_name"] for r in data["repositories"]] == ["acme/api"]
        assert data["install_url"] == "https://github.com/apps/docsgpt-acme/installations/new"

    def test_rejected_token_asks_to_reconnect(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionRepositories

        cid = _connection(pg_conn)
        with _db(pg_conn), patch("docsgpt.connectors.github.requests.get",
                                 return_value=_response({"message": "Bad credentials"}, 401)), \
                patch.object(service, "mark_reconnect_needed") as flag:
            resp = _call(app, ConnectionRepositories, "get", f"/api/connections/{cid}/repositories", args=[cid])
        assert resp.status_code == 409
        flag.assert_called_once()

    def test_only_the_owner_and_only_github(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionRepositories

        cid = _connection(pg_conn, user="bob")
        with _db(pg_conn):
            resp = _call(app, ConnectionRepositories, "get", f"/api/connections/{cid}/repositories", args=[cid])
        assert resp.status_code == 404


class TestSetup:
    def test_sync_queues_the_repository_with_the_connection(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn)
        with _db(pg_conn), patch("docsgpt.api.user.tasks.ingest_remote.apply_async",
                                 return_value=MagicMock(id="t")) as apply:
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup", body={
                "create_tools": False,
                "sync": {"items": {"repo_url": "https://github.com/octocat/private.git"}, "frequency": "daily"},
            }, args=[cid])
        assert resp.status_code == 200
        kwargs = apply.call_args.kwargs["kwargs"]
        assert kwargs["loader"] == "github"
        assert kwargs["source_data"] == {"repo_url": "octocat/private"}
        assert kwargs["connection_id"] == cid
        assert kwargs["sync_frequency"] == "daily"
        # Named after the repository, not the connector.
        assert resp.get_json()["sources"][0]["name"] == "octocat/private"

    def test_not_a_repository_is_a_bad_request(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn)
        with _db(pg_conn):
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup", body={
                "create_tools": False, "sync": {"items": {"repo_url": "https://example.com/x"}},
            }, args=[cid])
        assert resp.status_code == 400

    def test_tools_are_the_read_only_mcp_server_with_discovered_actions(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn)
        actions = [{"name": "get_file_contents", "description": "Read a file", "annotations": {"readOnlyHint": True},
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}]
        with _db(pg_conn), patch("docsgpt.agents.tools.mcp_tool.MCPTool.discover_tools"), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.get_actions_metadata", return_value=actions), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool.__init__", return_value=None) as init:
            for _ in range(2):
                resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                             body={"create_tools": True}, args=[cid])
        assert resp.status_code == 200
        # The first MCPTool is the discovery one (the tool registry builds more).
        config = init.call_args_list[0].args[0]
        assert config["server_url"] == READONLY_MCP
        assert config["auth_credentials"] == {"access_token": "github_pat_alice"}
        rows = pg_conn.execute(text(
            "SELECT name, config, actions FROM user_tools WHERE connection_id = CAST(:c AS uuid)"
        ), {"c": cid}).all()
        assert len(rows) == 1
        name, stored, stored_actions = rows[0]
        assert name == "mcp_tool"
        assert stored == {"server_url": READONLY_MCP, "auth_type": "bearer", "transport_type": "http", "timeout": 30}
        assert "github_pat" not in str(stored)
        assert stored_actions[0]["name"] == "get_file_contents"
        assert stored_actions[0]["access"] == "read" and not stored_actions[0].get("require_approval")

    def test_unreachable_mcp_server_creates_nothing(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn)
        with _db(pg_conn), patch("docsgpt.connectors.mcp._discover", side_effect=RuntimeError("down")):
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                         body={"create_tools": True}, args=[cid])
        assert resp.status_code == 502
        assert resp.get_json()["code"] == "tools_unavailable"
        assert pg_conn.execute(text("SELECT count(*) FROM user_tools")).scalar() == 0


class TestToolRuntime:
    def _tool(self, cid, server_url=READONLY_MCP):
        return {
            "id": "tool-gh", "user_id": "alice", "name": "mcp_tool", "connection_id": cid,
            "config": {"server_url": server_url, "auth_type": "bearer"},
            "actions": [{"name": "get_me", "active": True}], "credential_mode": "owner",
        }

    def test_app_token_reaches_the_tool_as_a_bearer_token(self, pg_conn, app_settings):
        from docsgpt.agents.tool_executor import ToolExecutor

        cid = _connection(pg_conn, auth_kind="oauth", secrets={"token_info": {
            "access_token": "ghu_live", "expiry": "2099-01-01T00:00:00+00:00"}})
        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            ToolExecutor(user="alice")._get_or_load_tool(self._tool(cid), "t1", "get_me")
        config = manager.return_value.load_tool.call_args.kwargs["tool_config"]
        assert config["auth_credentials"] == {"access_token": "ghu_live"}
        assert config["server_url"] == READONLY_MCP

    def test_token_never_goes_to_another_server(self, pg_conn):
        from docsgpt.agents.tool_executor import ToolExecutor

        cid = _connection(pg_conn)
        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            with pytest.raises(service.ConnectionUnavailable):
                ToolExecutor(user="alice")._get_or_load_tool(
                    self._tool(cid, "https://evil.example.com/mcp"), "t1", "get_me",
                )
        manager.return_value.load_tool.assert_not_called()
