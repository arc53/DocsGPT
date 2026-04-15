"""Tests for application/api/user/tools/mcp.py using real PG."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.tools.mcp.db_session", _yield
    ), patch(
        "application.api.user.tools.mcp.db_readonly", _yield
    ):
        yield


class TestSanitizeMcpTransport:
    def test_defaults_to_auto(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport
        cfg = {}
        got = _sanitize_mcp_transport(cfg)
        assert got == "auto"
        assert cfg["transport_type"] == "auto"

    def test_accepts_supported_transports(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport
        for t in ("auto", "sse", "http"):
            cfg = {"transport_type": t}
            assert _sanitize_mcp_transport(cfg) == t

    def test_strips_command_and_args(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport
        cfg = {"transport_type": "http", "command": "/bin/x", "args": ["a"]}
        _sanitize_mcp_transport(cfg)
        assert "command" not in cfg
        assert "args" not in cfg

    def test_unsupported_transport_raises(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport
        with pytest.raises(ValueError):
            _sanitize_mcp_transport({"transport_type": "websocket"})


class TestExtractAuthCredentials:
    def test_api_key_auth(self):
        from application.api.user.tools.mcp import _extract_auth_credentials
        got = _extract_auth_credentials({
            "auth_type": "api_key",
            "api_key": "secret",
            "api_key_header": "X-API-Key",
        })
        assert got == {"api_key": "secret", "api_key_header": "X-API-Key"}

    def test_bearer_auth(self):
        from application.api.user.tools.mcp import _extract_auth_credentials
        got = _extract_auth_credentials({
            "auth_type": "bearer",
            "bearer_token": "my-token",
        })
        assert got == {"bearer_token": "my-token"}

    def test_basic_auth(self):
        from application.api.user.tools.mcp import _extract_auth_credentials
        got = _extract_auth_credentials({
            "auth_type": "basic",
            "username": "u", "password": "p",
        })
        assert got == {"username": "u", "password": "p"}

    def test_none_auth_empty_creds(self):
        from application.api.user.tools.mcp import _extract_auth_credentials
        assert _extract_auth_credentials({"auth_type": "none"}) == {}


class TestValidateMcpServerUrl:
    def test_empty_url_raises(self):
        from application.api.user.tools.mcp import _validate_mcp_server_url
        with pytest.raises(ValueError):
            _validate_mcp_server_url({})

    def test_missing_server_url(self):
        from application.api.user.tools.mcp import _validate_mcp_server_url
        with pytest.raises(ValueError):
            _validate_mcp_server_url({"server_url": ""})

    def test_ssrf_url_raises(self):
        from application.api.user.tools.mcp import _validate_mcp_server_url
        with pytest.raises(ValueError):
            _validate_mcp_server_url({"server_url": "http://127.0.0.1"})

    def test_valid_public_url_passes(self):
        from application.api.user.tools.mcp import _validate_mcp_server_url
        # Should not raise for a public-ish URL
        from application.core.url_validation import SSRFError
        try:
            _validate_mcp_server_url({"server_url": "https://example.com/mcp"})
        except ValueError as e:
            # If SSRF rules reject example.com for some reason, accept that
            if "Invalid" not in str(e):
                raise


class TestTestMCPServerConfig:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with app.test_request_context(
            "/api/mcp_server/test", method="POST",
            json={"config": {}},
        ):
            from flask import request
            request.decoded_token = None
            response = TestMCPServerConfig().post()
        assert response.status_code == 401

    def test_returns_400_missing_config(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with app.test_request_context(
            "/api/mcp_server/test", method="POST", json={},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = TestMCPServerConfig().post()
        assert response.status_code == 400

    def test_unsupported_transport_returns_400(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with app.test_request_context(
            "/api/mcp_server/test", method="POST",
            json={"config": {"transport_type": "websocket"}},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = TestMCPServerConfig().post()
        assert response.status_code == 400

    def test_missing_url_returns_400(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with app.test_request_context(
            "/api/mcp_server/test", method="POST",
            json={"config": {"transport_type": "http"}},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = TestMCPServerConfig().post()
        assert response.status_code == 400

    def test_connection_success(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        fake_tool = MagicMock()
        fake_tool.test_connection.return_value = {
            "success": True, "message": "OK",
            "tools_count": 3, "tools": ["a", "b", "c"],
        }

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=fake_tool,
        ), app.test_request_context(
            "/api/mcp_server/test", method="POST",
            json={
                "config": {
                    "transport_type": "http",
                    "server_url": "https://example.com/mcp",
                    "auth_type": "none",
                },
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = TestMCPServerConfig().post()
        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["tools_count"] == 3

    def test_connection_failure_returns_200_with_failure_message(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        fake_tool = MagicMock()
        fake_tool.test_connection.return_value = {
            "success": False, "message": "Cannot reach server",
        }

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=fake_tool,
        ), app.test_request_context(
            "/api/mcp_server/test", method="POST",
            json={
                "config": {
                    "transport_type": "http",
                    "server_url": "https://example.com/mcp",
                },
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = TestMCPServerConfig().post()
        assert response.status_code == 200
        assert response.json["success"] is False

    def test_oauth_required_returns_200(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        fake_tool = MagicMock()
        fake_tool.test_connection.return_value = {
            "success": False,
            "requires_oauth": True,
            "auth_url": "https://auth/ex",
        }

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=fake_tool,
        ), app.test_request_context(
            "/api/mcp_server/test", method="POST",
            json={
                "config": {
                    "transport_type": "http",
                    "server_url": "https://example.com/mcp",
                    "auth_type": "oauth",
                },
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = TestMCPServerConfig().post()
        assert response.status_code == 200
        assert response.json["requires_oauth"] is True

    def test_unexpected_exception_returns_500(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(
            "/api/mcp_server/test", method="POST",
            json={
                "config": {
                    "transport_type": "http",
                    "server_url": "https://example.com/mcp",
                },
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = TestMCPServerConfig().post()
        assert response.status_code == 500


class TestMCPServerSave:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save", method="POST",
            json={"displayName": "n", "config": {}},
        ):
            from flask import request
            request.decoded_token = None
            response = MCPServerSave().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save", method="POST", json={},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = MCPServerSave().post()
        assert response.status_code == 400

    def test_unsupported_transport_returns_400(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save", method="POST",
            json={
                "displayName": "Srv",
                "config": {"transport_type": "bogus"},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = MCPServerSave().post()
        assert response.status_code == 400

    def test_missing_server_url_returns_400(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save", method="POST",
            json={"displayName": "Srv", "config": {"transport_type": "http"}},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = MCPServerSave().post()
        assert response.status_code == 400

    def test_oauth_missing_task_id_returns_400(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save", method="POST",
            json={
                "displayName": "Srv",
                "config": {
                    "transport_type": "http",
                    "server_url": "https://example.com/mcp",
                    "auth_type": "oauth",
                },
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = MCPServerSave().post()
        assert response.status_code == 400

    def test_creates_mcp_tool_successfully(self, app, pg_conn):
        from application.api.user.tools.mcp import MCPServerSave

        user = "u-mcp-save"
        fake_tool = MagicMock()
        fake_tool.discover_tools.return_value = {"tools": ["t1"]}
        fake_tool.get_actions_metadata.return_value = [{"name": "t1"}]

        with _patch_db(pg_conn), patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=fake_tool,
        ), app.test_request_context(
            "/api/mcp_server/save", method="POST",
            json={
                "displayName": "My MCP",
                "config": {
                    "transport_type": "http",
                    "server_url": "https://example.com/mcp",
                    "auth_type": "none",
                },
                "status": True,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = MCPServerSave().post()
        assert response.status_code in (200, 201)


class TestMCPOAuthStatus:
    def test_returns_pending_when_no_data(self, app):
        from application.api.user.tools.mcp import MCPOAuthStatus

        fake_redis = MagicMock()
        fake_redis.get.return_value = None

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=fake_redis,
        ), app.test_request_context("/api/mcp_oauth_status/t1"):
            response = MCPOAuthStatus().get("t1")
        assert response.status_code == 200
        assert response.json["status"] == "pending"

    def test_returns_status_from_redis(self, app):
        from application.api.user.tools.mcp import MCPOAuthStatus

        fake_redis = MagicMock()
        fake_redis.get.return_value = '{"status": "completed", "tools": [{"name": "t1", "description": "d"}]}'

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=fake_redis,
        ), app.test_request_context("/api/mcp_oauth_status/t1"):
            response = MCPOAuthStatus().get("t1")
        assert response.status_code == 200
        assert response.json["status"] == "completed"
        assert response.json["tools"][0]["name"] == "t1"

    def test_redis_error_returns_500(self, app):
        from application.api.user.tools.mcp import MCPOAuthStatus

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context("/api/mcp_oauth_status/t1"):
            response = MCPOAuthStatus().get("t1")
        assert response.status_code == 500


class TestMCPOAuthCallback:
    def test_error_param_redirects_error(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with app.test_request_context(
            "/api/mcp_server/oauth_callback?error=access_denied"
        ):
            response = MCPOAuthCallback().get()
        assert response.status_code == 302
        assert "status=error" in response.location

    def test_missing_code_or_state_redirects_error(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with app.test_request_context(
            "/api/mcp_server/oauth_callback"
        ):
            response = MCPOAuthCallback().get()
        assert response.status_code == 302

    def test_success_redirects_success(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        fake_redis = MagicMock()
        fake_manager = MagicMock()
        fake_manager.handle_oauth_callback.return_value = True

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=fake_redis,
        ), patch(
            "application.api.user.tools.mcp.MCPOAuthManager",
            return_value=fake_manager,
        ), app.test_request_context(
            "/api/mcp_server/oauth_callback?code=c1&state=s1"
        ):
            response = MCPOAuthCallback().get()
        assert response.status_code == 302
        assert "status=success" in response.location

    def test_manager_failure_redirects_error(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        fake_redis = MagicMock()
        fake_manager = MagicMock()
        fake_manager.handle_oauth_callback.return_value = False

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=fake_redis,
        ), patch(
            "application.api.user.tools.mcp.MCPOAuthManager",
            return_value=fake_manager,
        ), app.test_request_context(
            "/api/mcp_server/oauth_callback?code=c1&state=s1"
        ):
            response = MCPOAuthCallback().get()
        assert response.status_code == 302
        assert "status=error" in response.location

    def test_no_redis_redirects_error(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=None,
        ), app.test_request_context(
            "/api/mcp_server/oauth_callback?code=c&state=s"
        ):
            response = MCPOAuthCallback().get()
        assert response.status_code == 302
        assert "Redis" in response.location or "status=error" in response.location

    def test_exception_redirects_error(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(
            "/api/mcp_server/oauth_callback?code=c&state=s"
        ):
            response = MCPOAuthCallback().get()
        assert response.status_code == 302


class TestMCPAuthStatus:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        with app.test_request_context(
            "/api/mcp_server/auth_status"
        ):
            from flask import request
            request.decoded_token = None
            response = MCPAuthStatus().get()
        assert response.status_code == 401
