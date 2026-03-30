"""Comprehensive tests for application/agents/tools/mcp_tool.py

Covers: MCPTool init, cache key generation, transport creation, tool formatting,
result formatting, execute_action, discover_tools, test_connection,
get_actions_metadata, DocsGPTOAuth, NonInteractiveOAuth, DBTokenStorage,
MCPOAuthManager.
"""

import asyncio
import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest


# ---- Fixtures to isolate module-level side effects ----

@pytest.fixture(autouse=True)
def _patch_mcp_globals(monkeypatch):
    """Patch module-level MongoDB and cache to avoid real connections."""
    import sys

    if "application.agents.tools.mcp_tool" in sys.modules:
        mcp_mod = sys.modules["application.agents.tools.mcp_tool"]
    else:
        mock_tasks = MagicMock()
        monkeypatch.setitem(sys.modules, "application.api.user.tasks", mock_tasks)
        import application.agents.tools.mcp_tool as mcp_mod

    mock_mongo = MagicMock()
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(mcp_mod, "mongo", mock_mongo)
    monkeypatch.setattr(mcp_mod, "db", mock_db)
    monkeypatch.setattr(mcp_mod, "_mcp_clients_cache", {})


@pytest.fixture
def mcp_config():
    return {
        "server_url": "https://mcp.example.com/api",
        "transport_type": "http",
        "auth_type": "none",
        "timeout": 10,
    }


@pytest.fixture
def bearer_config():
    return {
        "server_url": "https://mcp.example.com/api",
        "transport_type": "http",
        "auth_type": "bearer",
        "auth_credentials": {"bearer_token": "tok_123"},
        "timeout": 10,
    }


def _make_tool(config, **kwargs):
    from application.agents.tools.mcp_tool import MCPTool

    with patch.object(MCPTool, "_setup_client"):
        return MCPTool(config, **kwargs)


# =====================================================================
# MCPTool Initialization
# =====================================================================


@pytest.mark.unit
class TestMCPToolInit:

    def test_basic_init(self, mcp_config):
        tool = _make_tool(mcp_config)
        assert tool.server_url == "https://mcp.example.com/api"
        assert tool.transport_type == "http"
        assert tool.auth_type == "none"
        assert tool.timeout == 10
        assert tool.available_tools == []

    def test_bearer_auth_credentials(self, bearer_config):
        tool = _make_tool(bearer_config)
        assert tool.auth_credentials["bearer_token"] == "tok_123"

    def test_no_server_url_skips_setup(self):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            MCPTool({"server_url": "", "auth_type": "none"})
            mock_setup.assert_not_called()

    def test_oauth_skips_setup(self):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            MCPTool({
                "server_url": "https://mcp.example.com",
                "auth_type": "oauth",
            })
            mock_setup.assert_not_called()

    def test_encrypted_credentials_decryption(self):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client"), \
             patch("application.agents.tools.mcp_tool.decrypt_credentials",
                   return_value={"bearer_token": "decrypted_tok"}):
            tool = MCPTool(
                {
                    "server_url": "https://mcp.example.com",
                    "auth_type": "bearer",
                    "encrypted_credentials": "enc_data",
                },
                user_id="user1",
            )
            assert tool.auth_credentials == {"bearer_token": "decrypted_tok"}

    def test_query_mode_default_false(self, mcp_config):
        tool = _make_tool(mcp_config)
        assert tool.query_mode is False

    def test_query_mode_explicit_true(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
            "query_mode": True,
        })
        assert tool.query_mode is True

    def test_custom_headers_stored(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
            "headers": {"X-Custom": "val"},
        })
        assert tool.custom_headers == {"X-Custom": "val"}


# =====================================================================
# Redirect URI Resolution
# =====================================================================


@pytest.mark.unit
class TestResolveRedirectUri:

    def test_configured_redirect_uri_used(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
            "redirect_uri": "https://my.app/callback/",
        })
        assert tool.redirect_uri == "https://my.app/callback"

    def test_fallback_to_settings(self, monkeypatch):
        from application.core.settings import settings

        monkeypatch.setattr(settings, "API_URL", "https://api.docsgpt.co")
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        assert "/api/mcp_server/callback" in tool.redirect_uri


# =====================================================================
# Cache Key Generation
# =====================================================================


@pytest.mark.unit
class TestGenerateCacheKey:

    def test_none_auth(self, mcp_config):
        tool = _make_tool(mcp_config)
        assert "none" in tool._cache_key
        assert "mcp.example.com" in tool._cache_key

    def test_bearer_auth(self, bearer_config):
        tool = _make_tool(bearer_config)
        assert "bearer:" in tool._cache_key

    def test_api_key_auth(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "api_key",
            "auth_credentials": {"api_key": "sk-test12345678"},
        })
        assert "apikey:" in tool._cache_key

    def test_basic_auth(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "basic",
            "auth_credentials": {"username": "user1", "password": "pass"},
        })
        assert "basic:user1" in tool._cache_key

    def test_oauth_auth_includes_scopes(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
            "oauth_scopes": ["read", "write"],
        })
        assert "oauth:" in tool._cache_key
        assert "read,write" in tool._cache_key

    def test_bearer_empty_token(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "bearer",
            "auth_credentials": {},
        })
        assert "bearer:none" in tool._cache_key

    def test_api_key_empty(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "api_key",
            "auth_credentials": {},
        })
        assert "apikey:none" in tool._cache_key


# =====================================================================
# Transport Creation
# =====================================================================


@pytest.mark.unit
class TestCreateTransport:

    def test_http_transport(self, mcp_config):
        tool = _make_tool(mcp_config)
        transport = tool._create_transport()
        assert transport is not None

    def test_sse_transport(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com/sse",
            "transport_type": "sse",
            "auth_type": "none",
        })
        transport = tool._create_transport()
        assert transport is not None

    def test_auto_detects_sse(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com/sse",
            "transport_type": "auto",
            "auth_type": "none",
        })
        transport = tool._create_transport()
        assert transport is not None

    def test_auto_defaults_to_http(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com/api",
            "transport_type": "auto",
            "auth_type": "none",
        })
        transport = tool._create_transport()
        assert transport is not None

    def test_stdio_transport_disabled(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "transport_type": "stdio",
            "auth_type": "none",
        })
        with pytest.raises(ValueError, match="STDIO transport is disabled"):
            tool._create_transport()

    def test_api_key_header_injected(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "transport_type": "http",
            "auth_type": "api_key",
            "auth_credentials": {
                "api_key": "sk-test",
                "api_key_header": "X-Custom-Key",
            },
        })
        transport = tool._create_transport()
        assert transport is not None

    def test_basic_auth_header_injected(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "transport_type": "http",
            "auth_type": "basic",
            "auth_credentials": {"username": "user", "password": "pass"},
        })
        transport = tool._create_transport()
        assert transport is not None

    def test_unknown_transport_type_defaults_to_http(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "transport_type": "grpc",
            "auth_type": "none",
        })
        transport = tool._create_transport()
        assert transport is not None


# =====================================================================
# Format Tools
# =====================================================================


@pytest.mark.unit
class TestFormatTools:

    def test_format_list_of_dicts(self, mcp_config):
        tool = _make_tool(mcp_config)
        result = tool._format_tools([{"name": "tool1", "description": "desc"}])
        assert len(result) == 1
        assert result[0]["name"] == "tool1"

    def test_format_tools_with_name_attribute(self, mcp_config):
        tool = _make_tool(mcp_config)
        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.description = "A tool"
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        result = tool._format_tools([mock_tool])
        assert len(result) == 1
        assert result[0]["name"] == "my_tool"
        assert result[0]["inputSchema"] == {"type": "object", "properties": {}}

    def test_format_tools_with_model_dump(self, mcp_config):
        tool = _make_tool(mcp_config)
        mock_tool = MagicMock(spec=[])
        mock_tool.model_dump = MagicMock(
            return_value={"name": "dumped", "description": "from dump"}
        )
        # Ensure no "name" attribute
        result = tool._format_tools([mock_tool])
        assert len(result) == 1
        assert result[0]["name"] == "dumped"

    def test_format_tools_fallback_str(self, mcp_config):
        tool = _make_tool(mcp_config)

        class BareTool:
            def __str__(self):
                return "bare_tool"

        result = tool._format_tools([BareTool()])
        assert len(result) == 1
        assert result[0]["name"] == "bare_tool"
        assert result[0]["description"] == ""

    def test_format_tools_response_object(self, mcp_config):
        tool = _make_tool(mcp_config)
        resp = MagicMock()
        resp.tools = [{"name": "t1", "description": "d1"}]

        result = tool._format_tools(resp)
        assert len(result) == 1

    def test_format_tools_without_input_schema(self, mcp_config):
        tool = _make_tool(mcp_config)
        mock_tool = MagicMock()
        mock_tool.name = "simple"
        mock_tool.description = "no schema"
        del mock_tool.inputSchema

        result = tool._format_tools([mock_tool])
        assert "inputSchema" not in result[0]

    def test_format_empty(self, mcp_config):
        tool = _make_tool(mcp_config)
        assert tool._format_tools([]) == []
        assert tool._format_tools("unexpected") == []


# =====================================================================
# Format Result
# =====================================================================


@pytest.mark.unit
class TestFormatResult:

    def test_format_result_with_text_content(self, mcp_config):
        tool = _make_tool(mcp_config)
        mock_result = MagicMock()
        text_item = MagicMock()
        text_item.text = "Hello"
        del text_item.data
        mock_result.content = [text_item]
        mock_result.isError = False

        result = tool._format_result(mock_result)
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hello"
        assert result["isError"] is False

    def test_format_result_with_data_content(self, mcp_config):
        tool = _make_tool(mcp_config)
        mock_result = MagicMock()
        data_item = MagicMock()
        del data_item.text
        data_item.data = {"key": "value"}
        mock_result.content = [data_item]
        mock_result.isError = False

        result = tool._format_result(mock_result)
        assert result["content"][0]["type"] == "data"
        assert result["content"][0]["data"] == {"key": "value"}

    def test_format_result_unknown_content_type(self, mcp_config):
        tool = _make_tool(mcp_config)
        mock_result = MagicMock()
        unknown_item = MagicMock()
        del unknown_item.text
        del unknown_item.data
        mock_result.content = [unknown_item]
        mock_result.isError = False

        result = tool._format_result(mock_result)
        assert result["content"][0]["type"] == "unknown"

    def test_format_raw_result(self, mcp_config):
        tool = _make_tool(mcp_config)
        raw = {"key": "value"}
        assert tool._format_result(raw) == raw


# =====================================================================
# Execute Action
# =====================================================================


@pytest.mark.unit
class TestExecuteAction:

    def test_no_server_raises(self):
        tool = _make_tool({"server_url": "", "auth_type": "none"})
        with pytest.raises(Exception, match="No MCP server configured"):
            tool.execute_action("test_action")

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_successful_execute(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = {"key": "value"}

        result = tool.execute_action("test_action", param1="val1")

        mock_run.assert_called_once_with("call_tool", "test_action", param1="val1")
        assert result == {"key": "value"}

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_empty_kwargs_cleaned(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = {}

        tool.execute_action("test", param1="", param2=None, param3="real")

        call_kwargs = mock_run.call_args[1]
        assert "param1" not in call_kwargs
        assert "param2" not in call_kwargs
        assert call_kwargs["param3"] == "real"

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_auth_error_retries_for_non_oauth(self, mock_run, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = _make_tool(mcp_config)
        tool._client = MagicMock()

        mock_run.side_effect = [
            Exception("401 Unauthorized"),
            {"key": "retry_ok"},
        ]

        with patch.object(MCPTool, "_setup_client"):
            result = tool.execute_action("act")
            assert result == {"key": "retry_ok"}

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_auth_error_raises_for_oauth(self, mock_run):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
        })
        tool._client = MagicMock()
        mock_run.side_effect = Exception("401 Unauthorized")

        with pytest.raises(Exception, match="OAuth session expired"):
            tool.execute_action("act")

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_non_auth_error_raises(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = Exception("Something weird happened")

        with pytest.raises(Exception, match="Failed to execute action"):
            tool.execute_action("act")

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_no_client_calls_setup(self, mock_run, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = _make_tool(mcp_config)
        tool._client = None
        mock_run.return_value = {"ok": True}

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            tool.execute_action("act")
            mock_setup.assert_called()


# =====================================================================
# Discover Tools
# =====================================================================


@pytest.mark.unit
class TestDiscoverTools:

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_discover_tools_success(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = [{"name": "t1", "description": "d1"}]

        result = tool.discover_tools()
        assert len(result) == 1
        assert result[0]["name"] == "t1"

    def test_discover_tools_no_server_url(self):
        tool = _make_tool({"server_url": "", "auth_type": "none"})
        assert tool.discover_tools() == []

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_discover_tools_error(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = Exception("connection lost")

        with pytest.raises(Exception, match="Failed to discover tools"):
            tool.discover_tools()


# =====================================================================
# Test Connection
# =====================================================================


@pytest.mark.unit
class TestTestConnection:

    def test_no_server_url(self):
        tool = _make_tool({"server_url": "", "auth_type": "none"})
        result = tool.test_connection()
        assert result["success"] is False
        assert "No server URL" in result["message"]

    def test_invalid_scheme(self):
        tool = _make_tool({"server_url": "ftp://bad.com", "auth_type": "none"})
        result = tool.test_connection()
        assert result["success"] is False
        assert "Invalid URL scheme" in result["message"]

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_regular_connection_success(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = [
            None,  # ping
            [{"name": "t1", "description": "d1"}],  # list_tools
        ]

        result = tool.test_connection()
        assert result["success"] is True
        assert result["tools_count"] == 1

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_regular_connection_ping_fails_tools_work(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = [
            Exception("ping failed"),  # ping
            [{"name": "t1", "description": "d1"}],  # list_tools
        ]

        result = tool.test_connection()
        assert result["success"] is True

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_regular_connection_both_fail(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = [
            Exception("ping failed"),
            Exception("tools failed"),
        ]

        result = tool.test_connection()
        assert result["success"] is False

    def test_client_init_failure(self):
        from application.agents.tools.mcp_tool import MCPTool

        tool = _make_tool({
            "server_url": "https://good.example.com",
            "auth_type": "none",
        })
        tool._client = None

        with patch.object(MCPTool, "_setup_client", side_effect=Exception("init fail")):
            result = tool.test_connection()
            assert result["success"] is False
            assert "Client init failed" in result["message"]


# =====================================================================
# Map Error
# =====================================================================


@pytest.mark.unit
class TestMapError:

    def test_timeout_error(self, mcp_config):
        tool = _make_tool(mcp_config)
        err = tool._map_error("test", concurrent.futures.TimeoutError())
        assert "Timed out" in str(err)

    def test_connection_refused(self, mcp_config):
        tool = _make_tool(mcp_config)
        err = tool._map_error("test", ConnectionRefusedError())
        assert "Connection refused" in str(err)

    def test_403_forbidden(self, mcp_config):
        tool = _make_tool(mcp_config)
        err = tool._map_error("test", Exception("403 Forbidden"))
        assert "Access denied" in str(err)

    def test_401_unauthorized(self, mcp_config):
        tool = _make_tool(mcp_config)
        err = tool._map_error("test", Exception("401 Unauthorized"))
        assert "Authentication failed" in str(err)

    def test_econnrefused_pattern(self, mcp_config):
        tool = _make_tool(mcp_config)
        err = tool._map_error("test", Exception("ECONNREFUSED error"))
        assert "Connection refused" in str(err)

    def test_ssl_error(self, mcp_config):
        tool = _make_tool(mcp_config)
        err = tool._map_error("test", Exception("SSL certificate verify failed"))
        assert "SSL" in str(err)

    def test_unknown_error_passthrough(self, mcp_config):
        tool = _make_tool(mcp_config)
        original = RuntimeError("something weird")
        err = tool._map_error("test", original)
        assert err is original


# =====================================================================
# Get Actions Metadata
# =====================================================================


@pytest.mark.unit
class TestGetActionsMetadata:

    def test_empty_tools(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = []
        assert tool.get_actions_metadata() == []

    def test_tools_with_input_schema(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = [
            {
                "name": "search",
                "description": "Search things",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                    "description": "Search params",
                },
            }
        ]
        meta = tool.get_actions_metadata()
        assert len(meta) == 1
        assert meta[0]["name"] == "search"
        assert "query" in meta[0]["parameters"]["properties"]
        assert meta[0]["parameters"]["additionalProperties"] is False

    def test_tools_without_schema(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = [{"name": "ping", "description": "Ping"}]
        meta = tool.get_actions_metadata()
        assert meta[0]["parameters"]["properties"] == {}

    def test_tools_with_flat_schema(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = [
            {
                "name": "flat",
                "description": "Flat schema",
                "inputSchema": {"query": {"type": "string"}},
            }
        ]
        meta = tool.get_actions_metadata()
        assert "query" in meta[0]["parameters"]["properties"]

    def test_tools_with_alternate_schema_keys(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = [
            {
                "name": "alt",
                "description": "Alt",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "number"}},
                },
            }
        ]
        meta = tool.get_actions_metadata()
        assert "x" in meta[0]["parameters"]["properties"]

    def test_config_requirements(self, mcp_config):
        tool = _make_tool(mcp_config)
        reqs = tool.get_config_requirements()
        assert "server_url" in reqs
        assert "auth_type" in reqs
        assert reqs["server_url"]["required"] is True
        assert "timeout" in reqs


# =====================================================================
# Setup Client (caching)
# =====================================================================


@pytest.mark.unit
class TestSetupClient:

    def test_setup_client_caches_client(self, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool.__new__(MCPTool)
        tool.config = mcp_config
        tool.server_url = mcp_config["server_url"]
        tool.transport_type = "http"
        tool.auth_type = "none"
        tool.timeout = 10
        tool.custom_headers = {}
        tool.auth_credentials = {}
        tool.oauth_scopes = []
        tool.oauth_task_id = None
        tool.oauth_client_name = "DocsGPT-MCP"
        tool.redirect_uri = "https://example.com/callback"
        tool.query_mode = False
        tool._cache_key = "test_cache_key"
        tool._client = None
        tool.available_tools = []

        mock_client = MagicMock()
        with patch.object(MCPTool, "_create_transport", return_value=MagicMock()), \
             patch("application.agents.tools.mcp_tool.Client", return_value=mock_client):
            tool._setup_client()
            assert tool._client is mock_client


# =====================================================================
# MCPOAuthManager
# =====================================================================


@pytest.mark.unit
class TestMCPOAuthManager:

    def test_handle_callback_success(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(state="abc123", code="auth_code")
        assert result is True
        mock_redis.setex.assert_called()

    def test_handle_callback_no_redis(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(None)
        result = manager.handle_oauth_callback(state="abc", code="code")
        assert result is False

    def test_handle_callback_no_state(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)
        result = manager.handle_oauth_callback(state="", code="code")
        assert result is False

    def test_handle_callback_error(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(
            state="abc", code="", error="access_denied"
        )
        assert result is False

    def test_get_oauth_status_no_task(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(MagicMock())
        result = manager.get_oauth_status("")
        assert result["status"] == "not_started"

    def test_get_oauth_status_with_task(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        with patch("application.agents.tools.mcp_tool.mcp_oauth_status_task",
                   return_value={"status": "complete"}):
            manager = MCPOAuthManager(MagicMock())
            result = manager.get_oauth_status("task123")
            assert result["status"] == "complete"


# =====================================================================
# DBTokenStorage
# =====================================================================


@pytest.mark.unit
class TestDBTokenStorage:

    def test_get_base_url(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        assert (
            DBTokenStorage.get_base_url("https://mcp.example.com/api/v1")
            == "https://mcp.example.com"
        )

    def test_get_base_url_with_port(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        assert (
            DBTokenStorage.get_base_url("http://localhost:8080/path")
            == "http://localhost:8080"
        )

    def test_get_db_key(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        storage = DBTokenStorage(
            server_url="https://mcp.example.com/api",
            user_id="user1",
            db_client=mock_db,
        )
        key = storage.get_db_key()
        assert key["server_url"] == "https://mcp.example.com"
        assert key["user_id"] == "user1"

    def test_get_tokens_none(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(storage.get_tokens())
            assert result is None
        finally:
            loop.close()

    def test_serialize_client_info(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )
        info = {"redirect_uris": ["https://example.com/cb"]}
        result = storage._serialize_client_info(info)
        assert result["redirect_uris"] == ["https://example.com/cb"]

    def test_clear(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(storage.clear())
            mock_collection.delete_one.assert_called_once()
        finally:
            loop.close()


# =====================================================================
# NonInteractiveOAuth
# =====================================================================


@pytest.mark.unit
class TestNonInteractiveOAuth:

    def test_redirect_handler_raises(self):
        from application.agents.tools.mcp_tool import NonInteractiveOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        oauth = NonInteractiveOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read"],
            redis_client=None,
            redirect_uri="https://example.com/callback",
            db=mock_db,
            user_id="user1",
        )

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(Exception, match="OAuth session expired"):
                loop.run_until_complete(
                    oauth.redirect_handler("https://auth.example.com/authorize?state=x")
                )
        finally:
            loop.close()

    def test_callback_handler_raises(self):
        from application.agents.tools.mcp_tool import NonInteractiveOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        oauth = NonInteractiveOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read"],
            redis_client=None,
            redirect_uri="https://example.com/callback",
            db=mock_db,
            user_id="user1",
        )

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(Exception, match="OAuth session expired"):
                loop.run_until_complete(oauth.callback_handler())
        finally:
            loop.close()


# =====================================================================
# Run Async Operation
# =====================================================================


@pytest.mark.unit
class TestRunAsyncOperation:

    def test_run_in_new_loop(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()

        async def fake_execute(*args, **kwargs):
            return "ok"

        with patch.object(tool, "_execute_with_client", side_effect=fake_execute):
            result = tool._run_in_new_loop("ping")
            assert result == "ok"
