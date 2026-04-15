"""Unit tests for application.api.user.tools.mcp."""

import json
import uuid
from unittest.mock import Mock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.fixture(autouse=True)
def _bypass_url_validation():
    """Bypass SSRF URL validation so tests using localhost URLs can proceed."""
    with patch("application.api.user.tools.mcp.validate_url"):
        yield


# ---------------------------------------------------------------------------
# Helper: _sanitize_mcp_transport
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSanitizeMcpTransport:

    def test_defaults_to_auto(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport

        config = {}
        result = _sanitize_mcp_transport(config)
        assert result == "auto"
        assert config["transport_type"] == "auto"

    def test_accepts_sse(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport

        config = {"transport_type": "SSE"}
        result = _sanitize_mcp_transport(config)
        assert result == "sse"
        assert config["transport_type"] == "sse"

    def test_accepts_http(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport

        config = {"transport_type": "HTTP"}
        result = _sanitize_mcp_transport(config)
        assert result == "http"

    def test_rejects_unsupported_transport(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport

        config = {"transport_type": "stdio"}
        with pytest.raises(ValueError, match="Unsupported transport_type"):
            _sanitize_mcp_transport(config)

    def test_strips_command_and_args(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport

        config = {
            "transport_type": "auto",
            "command": "/usr/bin/mcp",
            "args": ["--flag"],
        }
        _sanitize_mcp_transport(config)
        assert "command" not in config
        assert "args" not in config

    def test_handles_none_transport_type(self):
        from application.api.user.tools.mcp import _sanitize_mcp_transport

        config = {"transport_type": None}
        result = _sanitize_mcp_transport(config)
        assert result == "auto"


# ---------------------------------------------------------------------------
# Helper: _extract_auth_credentials
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestExtractAuthCredentials:

    def test_api_key_auth(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {
            "auth_type": "api_key",
            "api_key": "my-key",
            "api_key_header": "X-API-Key",
        }
        result = _extract_auth_credentials(config)
        assert result == {"api_key": "my-key", "api_key_header": "X-API-Key"}

    def test_api_key_auth_only_key(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {"auth_type": "api_key", "api_key": "my-key"}
        result = _extract_auth_credentials(config)
        assert result == {"api_key": "my-key"}
        assert "api_key_header" not in result

    def test_bearer_auth(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {"auth_type": "bearer", "bearer_token": "tok123"}
        result = _extract_auth_credentials(config)
        assert result == {"bearer_token": "tok123"}

    def test_bearer_auth_empty_token(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {"auth_type": "bearer"}
        result = _extract_auth_credentials(config)
        assert result == {}

    def test_basic_auth(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {"auth_type": "basic", "username": "user", "password": "pass"}
        result = _extract_auth_credentials(config)
        assert result == {"username": "user", "password": "pass"}

    def test_basic_auth_partial(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {"auth_type": "basic", "username": "user"}
        result = _extract_auth_credentials(config)
        assert result == {"username": "user"}

    def test_none_auth(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {"auth_type": "none"}
        result = _extract_auth_credentials(config)
        assert result == {}

    def test_default_no_auth_type(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {}
        result = _extract_auth_credentials(config)
        assert result == {}

    def test_unknown_auth_type(self):
        from application.api.user.tools.mcp import _extract_auth_credentials

        config = {"auth_type": "oauth"}
        result = _extract_auth_credentials(config)
        assert result == {}


# ---------------------------------------------------------------------------
# Route: TestMCPServerConfig
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTestMCPServerConfig:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with app.test_request_context(
            "/api/mcp_server/test",
            method="POST",
            json={"config": {}},
        ):
            from flask import request

            request.decoded_token = None
            response = TestMCPServerConfig().post()

        assert response.status_code == 401

    def test_returns_400_missing_config(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with app.test_request_context(
            "/api/mcp_server/test",
            method="POST",
            json={},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = TestMCPServerConfig().post()

        assert response.status_code == 400

    def test_returns_400_unsupported_transport(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with app.test_request_context(
            "/api/mcp_server/test",
            method="POST",
            json={"config": {"transport_type": "stdio"}},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = TestMCPServerConfig().post()

        assert response.status_code == 400
        assert "Unsupported transport_type" in response.json["error"]

    def test_successful_connection_test(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        mock_mcp_tool = Mock()
        mock_mcp_tool.test_connection.return_value = {
            "success": True,
            "tools_count": 3,
        }

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ):
            with app.test_request_context(
                "/api/mcp_server/test",
                method="POST",
                json={
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "http",
                        "auth_type": "none",
                    }
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = TestMCPServerConfig().post()

        assert response.status_code == 200
        assert response.json["success"] is True

    def test_returns_oauth_required(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        mock_mcp_tool = Mock()
        mock_mcp_tool.test_connection.return_value = {
            "requires_oauth": True,
            "authorization_url": "https://auth.example.com",
        }

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ):
            with app.test_request_context(
                "/api/mcp_server/test",
                method="POST",
                json={
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    }
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = TestMCPServerConfig().post()

        assert response.status_code == 200
        assert response.json["requires_oauth"] is True

    def test_redacts_failure_message(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        mock_mcp_tool = Mock()
        mock_mcp_tool.test_connection.return_value = {
            "success": False,
            "message": "SSL certificate verify failed",
        }

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ):
            with app.test_request_context(
                "/api/mcp_server/test",
                method="POST",
                json={
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    }
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = TestMCPServerConfig().post()

        assert response.status_code == 200
        assert response.json["message"] == "Connection test failed"

    def test_returns_500_on_exception(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            side_effect=RuntimeError("boom"),
        ):
            with app.test_request_context(
                "/api/mcp_server/test",
                method="POST",
                json={
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    }
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = TestMCPServerConfig().post()

        assert response.status_code == 500
        assert "Connection test failed" in response.json["error"]

    def test_passes_auth_credentials_to_mcp_tool(self, app):
        from application.api.user.tools.mcp import TestMCPServerConfig

        mock_mcp_tool = Mock()
        mock_mcp_tool.test_connection.return_value = {"success": True}

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ) as mock_cls:
            with app.test_request_context(
                "/api/mcp_server/test",
                method="POST",
                json={
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "http",
                        "auth_type": "bearer",
                        "bearer_token": "tok123",
                    }
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = TestMCPServerConfig().post()

        assert response.status_code == 200
        call_kwargs = mock_cls.call_args
        config_arg = call_kwargs[1]["config"] if "config" in call_kwargs[1] else call_kwargs[0][0]
        assert config_arg["auth_credentials"]["bearer_token"] == "tok123"


# ---------------------------------------------------------------------------
# Route: MCPServerSave
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMCPServerSave:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save",
            method="POST",
            json={"displayName": "My MCP", "config": {}},
        ):
            from flask import request

            request.decoded_token = None
            response = MCPServerSave().post()

        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save",
            method="POST",
            json={"displayName": "My MCP"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = MCPServerSave().post()

        assert response.status_code == 400

    def test_returns_400_unsupported_transport(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save",
            method="POST",
            json={
                "displayName": "My MCP",
                "config": {"transport_type": "stdio"},
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = MCPServerSave().post()

        assert response.status_code == 400
        assert "Unsupported transport_type" in response.json["error"]

    def test_creates_new_mcp_server_no_auth(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        inserted_id = uuid.uuid4().hex
        mock_mcp_tool = Mock()
        mock_mcp_tool.discover_tools.return_value = None
        mock_mcp_tool.get_actions_metadata.return_value = [
            {"name": "tool1", "parameters": {"properties": {"q": {"type": "string"}}}},
        ]
        mock_collection = Mock()
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "displayName": "My MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["id"] == str(inserted_id)
        assert response.json["tools_count"] == 1
        mock_collection.insert_one.assert_called_once()

    def test_creates_with_bearer_auth(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        inserted_id = uuid.uuid4().hex
        mock_mcp_tool = Mock()
        mock_mcp_tool.discover_tools.return_value = None
        mock_mcp_tool.get_actions_metadata.return_value = []
        mock_collection = Mock()
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.mcp.encrypt_credentials",
            return_value="enc-blob",
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "displayName": "My MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "bearer",
                        "bearer_token": "tok123",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 200
        call_arg = mock_collection.insert_one.call_args[0][0]
        assert call_arg["config"]["encrypted_credentials"] == "enc-blob"
        assert "bearer_token" not in call_arg["config"]

    def test_updates_existing_mcp_server(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        tool_id = uuid.uuid4().hex
        mock_mcp_tool = Mock()
        mock_mcp_tool.discover_tools.return_value = None
        mock_mcp_tool.get_actions_metadata.return_value = [
            {"name": "tool1"},
            {"name": "tool2"},
        ]
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "config": {},
        }
        mock_collection.update_one.return_value = Mock(matched_count=1)

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "id": str(tool_id),
                    "displayName": "Updated MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 200
        assert response.json["id"] == str(tool_id)
        assert response.json["tools_count"] == 2
        assert "updated" in response.json["message"].lower()

    def test_returns_404_update_not_found(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        tool_id = uuid.uuid4().hex
        mock_mcp_tool = Mock()
        mock_mcp_tool.discover_tools.return_value = None
        mock_mcp_tool.get_actions_metadata.return_value = []
        mock_collection = Mock()
        mock_collection.find_one.return_value = None
        mock_collection.update_one.return_value = Mock(matched_count=0)

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "id": str(tool_id),
                    "displayName": "MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 404

    def test_oauth_auth_without_task_id(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save",
            method="POST",
            json={
                "displayName": "MCP",
                "config": {
                    "server_url": "http://localhost:8080",
                    "transport_type": "auto",
                    "auth_type": "oauth",
                },
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = MCPServerSave().post()

        assert response.status_code == 400
        assert "OAuth authorization" in response.json["error"]

    def test_oauth_auth_not_completed(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        mock_manager = Mock()
        mock_manager.get_oauth_status.return_value = {"status": "pending"}

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=Mock(),
        ), patch(
            "application.api.user.tools.mcp.MCPOAuthManager",
            return_value=mock_manager,
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "displayName": "MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "oauth",
                        "oauth_task_id": "task123",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 400
        assert "OAuth failed" in response.json["error"]

    def test_oauth_auth_completed_successfully(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        inserted_id = uuid.uuid4().hex
        mock_manager = Mock()
        mock_manager.get_oauth_status.return_value = {
            "status": "completed",
            "tools": [{"name": "tool1"}],
        }
        mock_collection = Mock()
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=Mock(),
        ), patch(
            "application.api.user.tools.mcp.MCPOAuthManager",
            return_value=mock_manager,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "displayName": "MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "oauth",
                        "oauth_task_id": "task123",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 200
        assert response.json["success"] is True

    def test_no_credentials_for_non_none_auth_raises(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with app.test_request_context(
            "/api/mcp_server/save",
            method="POST",
            json={
                "displayName": "MCP",
                "config": {
                    "server_url": "http://localhost:8080",
                    "transport_type": "auto",
                    "auth_type": "bearer",
                },
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = MCPServerSave().post()

        assert response.status_code == 500

    def test_returns_500_on_exception(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            side_effect=RuntimeError("boom"),
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "displayName": "MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 500
        assert "Failed to save MCP server" in response.json["error"]

    def test_strips_sensitive_fields_from_storage(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        inserted_id = uuid.uuid4().hex
        mock_mcp_tool = Mock()
        mock_mcp_tool.discover_tools.return_value = None
        mock_mcp_tool.get_actions_metadata.return_value = []
        mock_collection = Mock()
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.mcp.encrypt_credentials",
            return_value="enc",
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "displayName": "MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "api_key",
                        "api_key": "secret",
                        "api_key_header": "X-Key",
                        "username": "u",
                        "password": "p",
                        "bearer_token": "bt",
                        "redirect_uri": "http://cb",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 200
        stored_config = mock_collection.insert_one.call_args[0][0]["config"]
        for field in ["api_key", "bearer_token", "username", "password", "api_key_header", "redirect_uri"]:
            assert field not in stored_config

    def test_merges_existing_encrypted_credentials_on_update(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        tool_id = uuid.uuid4().hex
        mock_mcp_tool = Mock()
        mock_mcp_tool.discover_tools.return_value = None
        mock_mcp_tool.get_actions_metadata.return_value = []
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "config": {"encrypted_credentials": "old-enc"},
        }
        mock_collection.update_one.return_value = Mock(matched_count=1)

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.mcp.decrypt_credentials",
            return_value={"api_key": "old-key"},
        ), patch(
            "application.api.user.tools.mcp.encrypt_credentials",
            return_value="merged-enc",
        ) as mock_encrypt:
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "id": str(tool_id),
                    "displayName": "MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "api_key",
                        "api_key": "new-key",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 200
        merged_call = mock_encrypt.call_args[0][0]
        assert merged_call["api_key"] == "new-key"

    def test_preserves_existing_encrypted_when_no_new_credentials(self, app):
        from application.api.user.tools.mcp import MCPServerSave

        tool_id = uuid.uuid4().hex
        mock_mcp_tool = Mock()
        mock_mcp_tool.discover_tools.return_value = None
        mock_mcp_tool.get_actions_metadata.return_value = []
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": tool_id,
            "config": {"encrypted_credentials": "existing-enc"},
        }
        mock_collection.update_one.return_value = Mock(matched_count=1)

        with patch(
            "application.api.user.tools.mcp.MCPTool",
            return_value=mock_mcp_tool,
        ), patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/mcp_server/save",
                method="POST",
                json={
                    "id": str(tool_id),
                    "displayName": "MCP",
                    "config": {
                        "server_url": "http://localhost:8080",
                        "transport_type": "auto",
                        "auth_type": "none",
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPServerSave().post()

        assert response.status_code == 200
        update_call = mock_collection.update_one.call_args[0][1]["$set"]
        assert update_call["config"]["encrypted_credentials"] == "existing-enc"


# ---------------------------------------------------------------------------
# Route: MCPOAuthCallback
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMCPOAuthCallback:

    def test_redirects_on_error_param(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with app.test_request_context(
            "/api/mcp_server/callback?error=access_denied&code=abc&state=xyz"
        ):
            response = MCPOAuthCallback().get()

        assert response.status_code == 302
        assert "error" in response.headers["Location"]
        assert "access_denied" in response.headers["Location"]

    def test_redirects_on_missing_code_or_state(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with app.test_request_context("/api/mcp_server/callback"):
            response = MCPOAuthCallback().get()

        assert response.status_code == 302
        assert "error" in response.headers["Location"]

    def test_redirects_on_missing_code(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with app.test_request_context("/api/mcp_server/callback?state=xyz"):
            response = MCPOAuthCallback().get()

        assert response.status_code == 302
        assert "error" in response.headers["Location"]

    def test_redirects_success_on_valid_callback(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        mock_manager = Mock()
        mock_manager.handle_oauth_callback.return_value = True

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=Mock(),
        ), patch(
            "application.api.user.tools.mcp.MCPOAuthManager",
            return_value=mock_manager,
        ):
            with app.test_request_context(
                "/api/mcp_server/callback?code=authcode&state=statetoken"
            ):
                response = MCPOAuthCallback().get()

        assert response.status_code == 302
        assert "success" in response.headers["Location"]

    def test_redirects_error_on_failed_callback(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        mock_manager = Mock()
        mock_manager.handle_oauth_callback.return_value = False

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=Mock(),
        ), patch(
            "application.api.user.tools.mcp.MCPOAuthManager",
            return_value=mock_manager,
        ):
            with app.test_request_context(
                "/api/mcp_server/callback?code=authcode&state=statetoken"
            ):
                response = MCPOAuthCallback().get()

        assert response.status_code == 302
        assert "error" in response.headers["Location"]
        assert "failed" in response.headers["Location"].lower()

    def test_redirects_error_when_redis_unavailable(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=None,
        ):
            with app.test_request_context(
                "/api/mcp_server/callback?code=authcode&state=statetoken"
            ):
                response = MCPOAuthCallback().get()

        assert response.status_code == 302
        assert "Redis" in response.headers["Location"]

    def test_redirects_error_on_exception(self, app):
        from application.api.user.tools.mcp import MCPOAuthCallback

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            side_effect=RuntimeError("redis down"),
        ):
            with app.test_request_context(
                "/api/mcp_server/callback?code=authcode&state=statetoken"
            ):
                response = MCPOAuthCallback().get()

        assert response.status_code == 302
        assert "error" in response.headers["Location"]


# ---------------------------------------------------------------------------
# Route: MCPOAuthStatus
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMCPOAuthStatus:

    def test_returns_pending_when_no_status(self, app):
        from application.api.user.tools.mcp import MCPOAuthStatus

        mock_redis = Mock()
        mock_redis.get.return_value = None

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=mock_redis,
        ):
            with app.test_request_context("/api/mcp_server/oauth_status/task123"):
                response = MCPOAuthStatus().get("task123")

        assert response.status_code == 200
        assert response.json["status"] == "pending"
        assert response.json["task_id"] == "task123"

    def test_returns_status_with_tools(self, app):
        from application.api.user.tools.mcp import MCPOAuthStatus

        status_data = {
            "status": "completed",
            "tools": [
                {"name": "tool1", "description": "desc1", "extra": "should_be_stripped"},
                {"name": "tool2", "description": "desc2"},
            ],
        }
        mock_redis = Mock()
        mock_redis.get.return_value = json.dumps(status_data)

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=mock_redis,
        ):
            with app.test_request_context("/api/mcp_server/oauth_status/task123"):
                response = MCPOAuthStatus().get("task123")

        assert response.status_code == 200
        assert response.json["status"] == "completed"
        tools = response.json["tools"]
        assert len(tools) == 2
        assert tools[0]["name"] == "tool1"
        assert "extra" not in tools[0]

    def test_returns_status_without_tools(self, app):
        from application.api.user.tools.mcp import MCPOAuthStatus

        status_data = {"status": "in_progress", "message": "Authorizing..."}
        mock_redis = Mock()
        mock_redis.get.return_value = json.dumps(status_data)

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            return_value=mock_redis,
        ):
            with app.test_request_context("/api/mcp_server/oauth_status/task123"):
                response = MCPOAuthStatus().get("task123")

        assert response.status_code == 200
        assert response.json["status"] == "in_progress"

    def test_returns_500_on_exception(self, app):
        from application.api.user.tools.mcp import MCPOAuthStatus

        with patch(
            "application.api.user.tools.mcp.get_redis_instance",
            side_effect=RuntimeError("redis down"),
        ):
            with app.test_request_context("/api/mcp_server/oauth_status/task123"):
                response = MCPOAuthStatus().get("task123")

        assert response.status_code == 500
        assert "Failed to get OAuth status" in response.json["error"]


# ---------------------------------------------------------------------------
# Route: MCPAuthStatus
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMCPAuthStatus:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        with app.test_request_context("/api/mcp_server/auth_status"):
            from flask import request

            request.decoded_token = None
            response = MCPAuthStatus().get()

        assert response.status_code == 401

    def test_returns_empty_statuses_when_no_mcp_tools(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        mock_collection = Mock()
        mock_collection.find.return_value = []

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        assert response.status_code == 200
        assert response.json["statuses"] == {}

    def test_returns_configured_for_non_oauth_tools(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        tool_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": tool_id,
                "config": {"auth_type": "api_key"},
            }
        ]

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        assert response.status_code == 200
        assert response.json["statuses"][str(tool_id)] == "configured"

    def test_returns_connected_for_oauth_with_tokens(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        tool_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": tool_id,
                "config": {
                    "auth_type": "oauth",
                    "server_url": "https://api.example.com/mcp",
                },
            }
        ]
        mock_sessions = Mock()
        mock_sessions.find.return_value = [
            {
                "server_url": "https://api.example.com",
                "tokens": {"access_token": "tok123"},
            }
        ]

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.mcp._connector_sessions",
            mock_sessions,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        assert response.status_code == 200
        assert response.json["statuses"][str(tool_id)] == "connected"

    def test_returns_needs_auth_for_oauth_without_tokens(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        tool_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": tool_id,
                "config": {
                    "auth_type": "oauth",
                    "server_url": "https://api.example.com/mcp",
                },
            }
        ]
        mock_sessions = Mock()
        mock_sessions.find.return_value = []

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.mcp._connector_sessions",
            mock_sessions,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        assert response.status_code == 200
        assert response.json["statuses"][str(tool_id)] == "needs_auth"

    def test_returns_needs_auth_for_oauth_without_server_url(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        tool_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": tool_id,
                "config": {"auth_type": "oauth", "server_url": ""},
            }
        ]

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        assert response.status_code == 200
        assert response.json["statuses"][str(tool_id)] == "needs_auth"

    def test_returns_configured_for_none_auth_type(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        tool_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {"_id": tool_id, "config": {}}
        ]

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        assert response.status_code == 200
        assert response.json["statuses"][str(tool_id)] == "configured"

    def test_returns_500_on_exception(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        mock_collection = Mock()
        mock_collection.find.side_effect = RuntimeError("db fail")

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        assert response.status_code == 500
        assert "Failed to check auth status" in response.json["error"]

    def test_multiple_tools_mixed_auth(self, app):
        from application.api.user.tools.mcp import MCPAuthStatus

        tool_id_1 = uuid.uuid4().hex
        tool_id_2 = uuid.uuid4().hex
        tool_id_3 = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {"_id": tool_id_1, "config": {"auth_type": "api_key"}},
            {
                "_id": tool_id_2,
                "config": {
                    "auth_type": "oauth",
                    "server_url": "https://api.example.com/mcp",
                },
            },
            {
                "_id": tool_id_3,
                "config": {
                    "auth_type": "oauth",
                    "server_url": "https://other.example.com/mcp",
                },
            },
        ]
        mock_sessions = Mock()
        mock_sessions.find.return_value = [
            {
                "server_url": "https://api.example.com",
                "tokens": {"access_token": "tok"},
            },
        ]

        with patch(
            "application.api.user.tools.mcp.user_tools_collection",
            mock_collection,
        ), patch(
            "application.api.user.tools.mcp._connector_sessions",
            mock_sessions,
        ):
            with app.test_request_context("/api/mcp_server/auth_status"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MCPAuthStatus().get()

        statuses = response.json["statuses"]
        assert statuses[str(tool_id_1)] == "configured"
        assert statuses[str(tool_id_2)] == "connected"
        assert statuses[str(tool_id_3)] == "needs_auth"
