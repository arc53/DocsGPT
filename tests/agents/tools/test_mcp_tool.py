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
    # Bypass DNS-resolving URL validation for tests using fake hostnames.
    monkeypatch.setattr(mcp_mod, "validate_url", lambda u, **kw: u)


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

    def test_rejects_metadata_ip(self, monkeypatch):
        from application.agents.tools.mcp_tool import MCPTool
        from application.core.url_validation import validate_url as real_validate_url
        import application.agents.tools.mcp_tool as mcp_mod

        monkeypatch.setattr(mcp_mod, "validate_url", real_validate_url)
        with pytest.raises(ValueError, match="Invalid MCP server URL"):
            MCPTool(config={"server_url": "http://169.254.169.254/latest/meta-data", "auth_type": "none"})

    def test_rejects_localhost(self, monkeypatch):
        from application.agents.tools.mcp_tool import MCPTool
        from application.core.url_validation import validate_url as real_validate_url
        import application.agents.tools.mcp_tool as mcp_mod

        monkeypatch.setattr(mcp_mod, "validate_url", real_validate_url)
        with pytest.raises(ValueError, match="Invalid MCP server URL"):
            MCPTool(config={"server_url": "http://localhost:8080/mcp", "auth_type": "none"})

    def test_rejects_private_ip(self, monkeypatch):
        from application.agents.tools.mcp_tool import MCPTool
        from application.core.url_validation import validate_url as real_validate_url
        import application.agents.tools.mcp_tool as mcp_mod

        monkeypatch.setattr(mcp_mod, "validate_url", real_validate_url)
        with pytest.raises(ValueError, match="Invalid MCP server URL"):
            MCPTool(config={"server_url": "http://10.0.0.1/mcp", "auth_type": "none"})

    def test_accepts_public_url(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com/api",
            "auth_type": "none",
        })
        assert tool.server_url == "https://mcp.example.com/api"

    def test_empty_server_url_allowed(self):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client"):
            tool = MCPTool(config={"server_url": "", "auth_type": "none"})
            assert tool.server_url == ""


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


# =====================================================================
# Resolve Redirect URI (additional coverage)
# =====================================================================


@pytest.mark.unit
class TestResolveRedirectUriExtended:

    def test_mcp_oauth_redirect_uri_setting(self, monkeypatch):
        from application.core.settings import settings

        monkeypatch.setattr(settings, "MCP_OAUTH_REDIRECT_URI", "https://custom.redirect/callback/")
        # Ensure no configured redirect_uri in config
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        assert tool.redirect_uri == "https://custom.redirect/callback"

    def test_connector_redirect_base_uri_setting(self, monkeypatch):
        from application.core.settings import settings

        monkeypatch.setattr(settings, "MCP_OAUTH_REDIRECT_URI", None, raising=False)
        monkeypatch.setattr(
            settings, "CONNECTOR_REDIRECT_BASE_URI",
            "https://connector.example.com/some/path",
        )
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        assert tool.redirect_uri == "https://connector.example.com/api/mcp_server/callback"

    def test_connector_redirect_base_uri_invalid_url(self, monkeypatch):
        from application.core.settings import settings

        monkeypatch.setattr(settings, "MCP_OAUTH_REDIRECT_URI", None, raising=False)
        # Provide a base URI that has no scheme
        monkeypatch.setattr(
            settings, "CONNECTOR_REDIRECT_BASE_URI", "no-scheme-url",
        )
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        # Falls through to API_URL fallback
        assert "/api/mcp_server/callback" in tool.redirect_uri


# =====================================================================
# _setup_client additional coverage (cache expiry, OAuth branches)
# =====================================================================


@pytest.mark.unit
class TestSetupClientExtended:

    def test_cache_hit_returns_cached_client(self):
        import application.agents.tools.mcp_tool as mcp_mod
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool.__new__(MCPTool)
        tool.config = {"server_url": "https://mcp.example.com", "auth_type": "none"}
        tool.server_url = "https://mcp.example.com"
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
        tool._cache_key = "cache_hit_test_key"
        tool._client = None
        tool.available_tools = []

        cached_client = MagicMock()
        mcp_mod._mcp_clients_cache["cache_hit_test_key"] = {
            "client": cached_client,
            "created_at": __import__("time").time(),
        }

        tool._setup_client()
        assert tool._client is cached_client

    def test_expired_cache_creates_new_client(self):
        import application.agents.tools.mcp_tool as mcp_mod
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool.__new__(MCPTool)
        tool.config = {"server_url": "https://mcp.example.com", "auth_type": "none"}
        tool.server_url = "https://mcp.example.com"
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
        tool._cache_key = "expired_cache_key"
        tool._client = None
        tool.available_tools = []

        old_client = MagicMock()
        mcp_mod._mcp_clients_cache["expired_cache_key"] = {
            "client": old_client,
            "created_at": __import__("time").time() - 600,
        }

        new_client = MagicMock()
        with patch.object(MCPTool, "_create_transport", return_value=MagicMock()), \
             patch("application.agents.tools.mcp_tool.Client", return_value=new_client):
            tool._setup_client()
            assert tool._client is new_client
            assert "expired_cache_key" not in mcp_mod._mcp_clients_cache or \
                mcp_mod._mcp_clients_cache["expired_cache_key"]["client"] is new_client

    def test_setup_client_oauth_query_mode(self):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool.__new__(MCPTool)
        tool.config = {"server_url": "https://mcp.example.com", "auth_type": "oauth"}
        tool.server_url = "https://mcp.example.com"
        tool.transport_type = "http"
        tool.auth_type = "oauth"
        tool.timeout = 10
        tool.custom_headers = {}
        tool.auth_credentials = {}
        tool.oauth_scopes = ["read"]
        tool.oauth_task_id = None
        tool.oauth_client_name = "DocsGPT-MCP"
        tool.redirect_uri = "https://example.com/callback"
        tool.query_mode = True
        tool._cache_key = "oauth_qm_key"
        tool._client = None
        tool.available_tools = []
        tool.user_id = "user1"

        mock_client = MagicMock()
        with patch.object(MCPTool, "_create_transport", return_value=MagicMock()), \
             patch("application.agents.tools.mcp_tool.Client", return_value=mock_client), \
             patch("application.agents.tools.mcp_tool.get_redis_instance", return_value=MagicMock()), \
             patch("application.agents.tools.mcp_tool.NonInteractiveOAuth"):
            tool._setup_client()
            assert tool._client is mock_client

    def test_setup_client_oauth_interactive_mode(self):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool.__new__(MCPTool)
        tool.config = {"server_url": "https://mcp.example.com", "auth_type": "oauth"}
        tool.server_url = "https://mcp.example.com"
        tool.transport_type = "http"
        tool.auth_type = "oauth"
        tool.timeout = 10
        tool.custom_headers = {}
        tool.auth_credentials = {}
        tool.oauth_scopes = ["read"]
        tool.oauth_task_id = "task123"
        tool.oauth_client_name = "DocsGPT-MCP"
        tool.redirect_uri = "https://example.com/callback"
        tool.query_mode = False
        tool._cache_key = "oauth_interactive_key"
        tool._client = None
        tool.available_tools = []
        tool.user_id = "user1"

        mock_client = MagicMock()
        with patch.object(MCPTool, "_create_transport", return_value=MagicMock()), \
             patch("application.agents.tools.mcp_tool.Client", return_value=mock_client), \
             patch("application.agents.tools.mcp_tool.get_redis_instance", return_value=MagicMock()), \
             patch("application.agents.tools.mcp_tool.DocsGPTOAuth"):
            tool._setup_client()
            assert tool._client is mock_client

    def test_setup_client_bearer_auth(self):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool.__new__(MCPTool)
        tool.config = {"server_url": "https://mcp.example.com", "auth_type": "bearer"}
        tool.server_url = "https://mcp.example.com"
        tool.transport_type = "http"
        tool.auth_type = "bearer"
        tool.timeout = 10
        tool.custom_headers = {}
        tool.auth_credentials = {"bearer_token": "my_token"}
        tool.oauth_scopes = []
        tool.oauth_task_id = None
        tool.oauth_client_name = "DocsGPT-MCP"
        tool.redirect_uri = "https://example.com/callback"
        tool.query_mode = False
        tool._cache_key = "bearer_setup_key"
        tool._client = None
        tool.available_tools = []

        mock_client = MagicMock()
        with patch.object(MCPTool, "_create_transport", return_value=MagicMock()), \
             patch("application.agents.tools.mcp_tool.Client", return_value=mock_client), \
             patch("application.agents.tools.mcp_tool.BearerAuth") as mock_bearer_auth:
            tool._setup_client()
            mock_bearer_auth.assert_called_once_with("my_token")
            assert tool._client is mock_client


# =====================================================================
# _execute_with_client async coverage
# =====================================================================


@pytest.mark.unit
class TestExecuteWithClient:

    @staticmethod
    def _make_async_client():
        """Create a mock client that supports async context manager."""
        from unittest.mock import AsyncMock as AM

        mock_client = MagicMock()
        mock_client.__aenter__ = AM(return_value=mock_client)
        mock_client.__aexit__ = AM(return_value=None)
        return mock_client

    def test_ping_operation(self, mcp_config):
        from unittest.mock import AsyncMock as AM

        tool = _make_tool(mcp_config)
        mock_client = self._make_async_client()
        mock_client.ping = AM(return_value="pong")
        tool._client = mock_client

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(tool._execute_with_client("ping"))
            assert result == "pong"
        finally:
            loop.close()

    def test_list_tools_operation(self, mcp_config):
        from unittest.mock import AsyncMock as AM

        tool = _make_tool(mcp_config)
        mock_client = self._make_async_client()
        mock_client.list_tools = AM(return_value=[{"name": "t1", "description": "d1"}])
        tool._client = mock_client

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(tool._execute_with_client("list_tools"))
            assert len(result) == 1
        finally:
            loop.close()

    def test_call_tool_operation(self, mcp_config):
        from unittest.mock import AsyncMock as AM

        tool = _make_tool(mcp_config)
        mock_client = self._make_async_client()
        mock_client.call_tool = AM(return_value={"result": "called my_action"})
        tool._client = mock_client

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                tool._execute_with_client("call_tool", "my_action", key="val")
            )
            assert result == {"result": "called my_action"}
        finally:
            loop.close()

    def test_list_resources_operation(self, mcp_config):
        from unittest.mock import AsyncMock as AM

        tool = _make_tool(mcp_config)
        mock_client = self._make_async_client()
        mock_client.list_resources = AM(return_value=["r1", "r2"])
        tool._client = mock_client

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(tool._execute_with_client("list_resources"))
            assert result == ["r1", "r2"]
        finally:
            loop.close()

    def test_list_prompts_operation(self, mcp_config):
        from unittest.mock import AsyncMock as AM

        tool = _make_tool(mcp_config)
        mock_client = self._make_async_client()
        mock_client.list_prompts = AM(return_value=["p1"])
        tool._client = mock_client

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(tool._execute_with_client("list_prompts"))
            assert result == ["p1"]
        finally:
            loop.close()

    def test_unknown_operation_raises(self, mcp_config):
        tool = _make_tool(mcp_config)
        mock_client = self._make_async_client()
        tool._client = mock_client

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(Exception, match="Unknown operation"):
                loop.run_until_complete(tool._execute_with_client("bogus_op"))
        finally:
            loop.close()

    def test_no_client_raises(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = None

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(Exception, match="not initialized"):
                loop.run_until_complete(tool._execute_with_client("ping"))
        finally:
            loop.close()


# =====================================================================
# _run_async_operation (error mapping path)
# =====================================================================


@pytest.mark.unit
class TestRunAsyncOperationExtended:

    def test_error_is_mapped_and_raised(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()

        with patch.object(tool, "_run_in_new_loop", side_effect=ConnectionRefusedError()):
            with pytest.raises(Exception, match="Connection refused"):
                tool._run_async_operation("ping")

    def test_inside_running_loop_uses_thread_pool(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()

        # Simulate being inside a running event loop
        with patch("asyncio.get_running_loop", return_value=MagicMock()), \
             patch("concurrent.futures.ThreadPoolExecutor") as mock_tp:
            mock_future = MagicMock()
            mock_future.result.return_value = "thread_result"
            mock_executor = MagicMock()
            mock_executor.__enter__ = MagicMock(return_value=mock_executor)
            mock_executor.__exit__ = MagicMock(return_value=False)
            mock_executor.submit.return_value = mock_future
            mock_tp.return_value = mock_executor

            result = tool._run_async_operation("ping")
            assert result == "thread_result"


# =====================================================================
# test_connection additional coverage
# =====================================================================


@pytest.mark.unit
class TestTestConnectionExtended:

    def test_url_parse_exception(self):
        """Test that an unparseable URL returns failure."""
        tool = _make_tool({"server_url": "://bad", "auth_type": "none"})
        result = tool.test_connection()
        assert result["success"] is False

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_no_tools_and_no_ping_fails(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        # ping succeeds but discover_tools returns empty
        mock_run.side_effect = [
            None,  # ping ok
        ]
        with patch.object(tool, "discover_tools", return_value=[]):
            result = tool.test_connection()
            # ping_ok is True but tools is empty, should still succeed
            assert result["success"] is True

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_ping_fails_no_tools_fails(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = [
            Exception("ping failed"),
        ]
        with patch.object(tool, "discover_tools", return_value=[]):
            result = tool.test_connection()
            assert result["success"] is False
            assert "ping failed" in result["message"]

    def test_oauth_connection_with_valid_tokens(self):
        from application.agents.tools.mcp_tool import MCPTool

        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
            "oauth_scopes": ["read"],
        })
        tool.user_id = "user1"
        tool._client = MagicMock()

        mock_token = MagicMock()
        mock_token.access_token = "valid_token"

        with patch("application.agents.tools.mcp_tool.DBTokenStorage") as mock_storage_cls:
            mock_storage = MagicMock()

            async def fake_get_tokens():
                return mock_token

            mock_storage.get_tokens = fake_get_tokens
            mock_storage_cls.return_value = mock_storage

            with patch.object(tool, "discover_tools", return_value=[{"name": "t1", "description": "d1"}]), \
                 patch.object(MCPTool, "_setup_client"):
                result = tool.test_connection()
                assert result["success"] is True
                assert result["tools_count"] == 1

    def test_oauth_connection_with_expired_tokens_starts_task(self):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
            "oauth_scopes": ["read"],
        })
        tool.user_id = "user1"
        tool._client = MagicMock()

        with patch("application.agents.tools.mcp_tool.DBTokenStorage") as mock_storage_cls:
            mock_storage = MagicMock()

            async def fake_get_tokens():
                return None

            mock_storage.get_tokens = fake_get_tokens
            mock_storage_cls.return_value = mock_storage

            mock_task_result = MagicMock()
            mock_task_result.id = "task_abc"
            with patch("application.agents.tools.mcp_tool.mcp_oauth_task") as mock_task:
                mock_task.delay.return_value = mock_task_result
                result = tool.test_connection()
                assert result["success"] is False
                assert result["requires_oauth"] is True
                assert result["task_id"] == "task_abc"

    def test_oauth_connection_token_validation_fails(self):
        from application.agents.tools.mcp_tool import MCPTool

        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
            "oauth_scopes": ["read"],
        })
        tool.user_id = "user1"
        tool._client = MagicMock()

        mock_token = MagicMock()
        mock_token.access_token = "expired_token"

        with patch("application.agents.tools.mcp_tool.DBTokenStorage") as mock_storage_cls:
            mock_storage = MagicMock()

            async def fake_get_tokens():
                return mock_token

            mock_storage.get_tokens = fake_get_tokens
            mock_storage_cls.return_value = mock_storage

            mock_task_result = MagicMock()
            mock_task_result.id = "task_retry"
            with patch.object(tool, "discover_tools", side_effect=Exception("401 Unauthorized")), \
                 patch.object(MCPTool, "_setup_client"), \
                 patch("application.agents.tools.mcp_tool.mcp_oauth_task") as mock_task:
                mock_task.delay.return_value = mock_task_result
                result = tool.test_connection()
                assert result["success"] is False
                assert result["requires_oauth"] is True


# =====================================================================
# execute_action extended (format_result path)
# =====================================================================


@pytest.mark.unit
class TestExecuteActionExtended:

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_execute_formats_result(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_result = MagicMock()
        text_item = MagicMock()
        text_item.text = "result text"
        del text_item.data
        mock_result.content = [text_item]
        mock_result.isError = False
        mock_run.return_value = mock_result

        result = tool.execute_action("test_action", query="hello")
        assert result["content"][0]["type"] == "text"
        assert result["isError"] is False

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_execute_auth_retry_second_attempt_fails(self, mock_run):
        from application.agents.tools.mcp_tool import MCPTool

        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "bearer",
            "auth_credentials": {"bearer_token": "tok"},
        })
        tool._client = MagicMock()

        mock_run.side_effect = Exception("401 Unauthorized")

        with patch.object(MCPTool, "_setup_client"):
            with pytest.raises(Exception, match="failed after re-auth attempt"):
                tool.execute_action("act")


# =====================================================================
# discover_tools extended
# =====================================================================


@pytest.mark.unit
class TestDiscoverToolsExtended:

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_discover_tools_no_client_calls_setup(self, mock_run, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = _make_tool(mcp_config)
        tool._client = None
        mock_run.return_value = [{"name": "t1", "description": "d1"}]

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            result = tool.discover_tools()
            mock_setup.assert_called_once()
            assert len(result) == 1


# =====================================================================
# _test_regular_connection extended
# =====================================================================


@pytest.mark.unit
class TestRegularConnectionExtended:

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_regular_connection_message_format(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = [None]  # ping ok
        with patch.object(tool, "discover_tools", return_value=[
            {"name": "single_tool", "description": "only one"},
        ]):
            result = tool.test_connection()
            assert result["success"] is True
            assert "1 tool" in result["message"]
            # Singular form for 1 tool
            assert "tools" not in result["message"]

    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_regular_connection_multiple_tools(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = [None]  # ping ok
        with patch.object(tool, "discover_tools", return_value=[
            {"name": "t1", "description": "d1"},
            {"name": "t2", "description": "d2"},
        ]):
            result = tool.test_connection()
            assert result["success"] is True
            assert "2 tools" in result["message"]
            assert len(result["tools"]) == 2


# =====================================================================
# DocsGPTOAuth extended
# =====================================================================


@pytest.mark.unit
class TestDocsGPTOAuthExtended:

    def test_process_auth_url_success(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read", "write"],
            redis_client=MagicMock(),
            redirect_uri="https://example.com/callback",
            task_id="task1",
            db=mock_db,
            user_id="user1",
        )

        url, state = oauth._process_auth_url(
            "https://auth.example.com/authorize?state=abc123&client_id=xyz"
        )
        assert state == "abc123"
        assert url == "https://auth.example.com/authorize?state=abc123&client_id=xyz"

    def test_process_auth_url_no_state(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes="read",
            redis_client=MagicMock(),
            redirect_uri="https://example.com/callback",
            db=mock_db,
            user_id="user1",
        )

        with pytest.raises(Exception, match="Failed to process auth URL"):
            oauth._process_auth_url("https://auth.example.com/authorize?client_id=xyz")

    def test_redirect_handler_stores_in_redis(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_redis = MagicMock()

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read"],
            redis_client=mock_redis,
            redirect_uri="https://example.com/callback",
            task_id="task1",
            db=mock_db,
            user_id="user1",
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                oauth.redirect_handler(
                    "https://auth.example.com/authorize?state=mystate&code=123"
                )
            )
        finally:
            loop.close()

        assert oauth.auth_url == "https://auth.example.com/authorize?state=mystate&code=123"
        assert oauth.extracted_state == "mystate"
        # Redis setex should have been called for auth_url and status
        assert mock_redis.setex.call_count >= 2

    def test_redirect_handler_no_redis(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read"],
            redis_client=None,
            redirect_uri="https://example.com/callback",
            db=mock_db,
            user_id="user1",
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                oauth.redirect_handler(
                    "https://auth.example.com/authorize?state=s1"
                )
            )
        finally:
            loop.close()

        assert oauth.extracted_state == "s1"

    def test_callback_handler_no_redis_raises(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read"],
            redis_client=None,
            redirect_uri="https://example.com/callback",
            db=mock_db,
            user_id="user1",
        )

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(Exception, match="Redis client or state not configured"):
                loop.run_until_complete(oauth.callback_handler())
        finally:
            loop.close()

    def test_callback_handler_receives_code(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_redis = MagicMock()
        # First get returns the code
        mock_redis.get.return_value = b"auth_code_123"

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read"],
            redis_client=mock_redis,
            redirect_uri="https://example.com/callback",
            task_id="task1",
            db=mock_db,
            user_id="user1",
        )
        oauth.extracted_state = "mystate"
        oauth.auth_url = "https://auth.example.com/authorize"

        loop = asyncio.new_event_loop()
        try:
            code, state = loop.run_until_complete(oauth.callback_handler())
            assert code == "auth_code_123"
            assert state == "mystate"
        finally:
            loop.close()

    def test_callback_handler_receives_error(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_redis = MagicMock()
        # First get for code returns None, second get for error returns error
        mock_redis.get.side_effect = [None, b"access_denied"]

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes=["read"],
            redis_client=mock_redis,
            redirect_uri="https://example.com/callback",
            db=mock_db,
            user_id="user1",
        )
        oauth.extracted_state = "mystate"
        oauth.auth_url = "https://auth.example.com/authorize"

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(Exception, match="OAuth error: access_denied"):
                loop.run_until_complete(oauth.callback_handler())
        finally:
            loop.close()

    def test_init_scopes_as_string(self):
        from application.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        oauth = DocsGPTOAuth(
            mcp_url="https://mcp.example.com/api",
            scopes="read write",
            redis_client=MagicMock(),
            redirect_uri="https://example.com/callback",
            db=mock_db,
            user_id="user1",
        )
        assert oauth.server_base_url == "https://mcp.example.com"


# =====================================================================
# DBTokenStorage extended
# =====================================================================


@pytest.mark.unit
class TestDBTokenStorageExtended:

    def test_get_tokens_with_valid_data(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "tokens": {
                "access_token": "at_123",
                "token_type": "bearer",
            }
        }
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(storage.get_tokens())
            assert result is not None
            assert result.access_token == "at_123"
        finally:
            loop.close()

    def test_get_tokens_with_invalid_data(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "tokens": {"bad_field": "bad_value"}
        }
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

    def test_set_tokens(self):
        from application.agents.tools.mcp_tool import DBTokenStorage
        from mcp.shared.auth import OAuthToken

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        token = OAuthToken(access_token="new_token", token_type="bearer")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(storage.set_tokens(token))
            mock_collection.update_one.assert_called_once()
        finally:
            loop.close()

    def test_get_client_info_none(self):
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
            result = loop.run_until_complete(storage.get_client_info())
            assert result is None
        finally:
            loop.close()

    def test_get_client_info_no_client_info_key(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {"tokens": {}}
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(storage.get_client_info())
            assert result is None
        finally:
            loop.close()

    def test_get_client_info_with_valid_data(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "client_info": {
                "client_id": "cid123",
                "redirect_uris": ["https://example.com/callback"],
            }
        }
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(storage.get_client_info())
            assert result is not None
            assert result.client_id == "cid123"
        finally:
            loop.close()

    def test_get_client_info_redirect_uri_mismatch(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "client_info": {
                "client_id": "cid123",
                "redirect_uris": ["https://old.example.com/callback"],
            }
        }
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
            expected_redirect_uri="https://new.example.com/callback",
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(storage.get_client_info())
            assert result is None
            mock_collection.update_one.assert_called_once()
        finally:
            loop.close()

    def test_get_client_info_invalid_data(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = {
            "client_info": {"invalid_key": "value"}
        }
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(storage.get_client_info())
            assert result is None
        finally:
            loop.close()

    def test_set_client_info(self):
        from application.agents.tools.mcp_tool import DBTokenStorage
        from mcp.shared.auth import OAuthClientInformationFull

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )

        client_info = OAuthClientInformationFull(
            client_id="cid123",
            redirect_uris=["https://example.com/callback"],
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(storage.set_client_info(client_info))
            mock_collection.update_one.assert_called_once()
        finally:
            loop.close()

    def test_clear_all(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(DBTokenStorage.clear_all(mock_db))
            mock_collection.delete_many.assert_called_once_with({})
        finally:
            loop.close()

    def test_serialize_client_info_without_redirect_uris(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
            db_client=mock_db,
        )
        info = {"client_name": "test"}
        result = storage._serialize_client_info(info)
        assert result == {"client_name": "test"}


# =====================================================================
# MCPOAuthManager extended
# =====================================================================


@pytest.mark.unit
class TestMCPOAuthManagerExtended:

    def test_handle_callback_redis_setex_for_state(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(state="s1", code="c1")
        assert result is True
        # Should call setex for code and state
        assert mock_redis.setex.call_count == 2

    def test_handle_callback_with_error_stores_error(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(
            state="s1", code="", error="invalid_scope"
        )
        assert result is False
        # Should store error in redis
        mock_redis.setex.assert_called()

    def test_get_oauth_status_task_error(self):
        from application.agents.tools.mcp_tool import MCPOAuthManager

        with patch(
            "application.agents.tools.mcp_tool.mcp_oauth_status_task",
            side_effect=Exception("task failed"),
        ):
            manager = MCPOAuthManager(MagicMock())
            with pytest.raises(Exception, match="task failed"):
                manager.get_oauth_status("task123")


# =====================================================================
# get_actions_metadata extended
# =====================================================================


@pytest.mark.unit
class TestGetActionsMetadataExtended:

    def test_tools_with_schema_key(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = [
            {
                "name": "schema_tool",
                "description": "Uses schema key",
                "schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            }
        ]
        meta = tool.get_actions_metadata()
        assert len(meta) == 1
        assert "q" in meta[0]["parameters"]["properties"]

    def test_tools_with_input_schema_key(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = [
            {
                "name": "is_tool",
                "description": "Uses input_schema key",
                "input_schema": {
                    "type": "object",
                    "properties": {"x": {"type": "number"}},
                },
            }
        ]
        meta = tool.get_actions_metadata()
        assert "x" in meta[0]["parameters"]["properties"]

    def test_multiple_tools(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool.available_tools = [
            {"name": "a", "description": "da"},
            {"name": "b", "description": "db", "inputSchema": {
                "type": "object",
                "properties": {"p": {"type": "string"}},
            }},
        ]
        meta = tool.get_actions_metadata()
        assert len(meta) == 2
        assert meta[0]["name"] == "a"
        assert meta[0]["parameters"]["properties"] == {}
        assert "p" in meta[1]["parameters"]["properties"]


# =====================================================================
# Coverage gap tests  (lines 207-210, 288-293, 346-347, 416-417, 620)
# =====================================================================


@pytest.mark.unit
class TestMCPToolGaps:

    def test_create_transport_stdio_raises(self, mcp_config):
        """Cover line 199-200: stdio transport raises ValueError."""
        mcp_config["transport_type"] = "stdio"
        tool = _make_tool(mcp_config)

        with pytest.raises(ValueError, match="STDIO transport is disabled"):
            tool._create_transport()

    def test_run_in_new_loop(self, mcp_config):
        """Cover lines 288-293: _run_in_new_loop creates a new event loop."""
        tool = _make_tool(mcp_config)

        async def dummy_operation(*args, **kwargs):
            return "result"

        tool._execute_with_client = dummy_operation
        result = tool._run_in_new_loop("test_op")
        assert result == "result"

    def test_execute_action_auth_error_retry(self, mcp_config):
        """Cover lines 346-347: auth error detection in execute_action."""
        tool = _make_tool(mcp_config)
        tool.available_tools = [{"name": "test_action"}]
        tool.auth_type = "bearer"

        call_count = 0

        def mock_run_async(operation, action_name, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("401 unauthorized")
            return MagicMock(content=[MagicMock(text="success")])

        tool._run_async_operation = mock_run_async
        tool._setup_client = MagicMock()

        result = tool.execute_action("test_action")
        assert "success" in str(result)

    def test_test_connection_invalid_url(self, mcp_config):
        """Cover lines 416-417: test_connection with invalid URL."""
        tool = _make_tool(mcp_config)
        tool.server_url = "not a url at all"
        tool._client = None

        result = tool.test_connection()
        assert result["success"] is False

    def test_get_config_requirements_has_username(self, mcp_config):
        """Cover line 620: config requirements include username field."""
        tool = _make_tool(mcp_config)
        config = tool.get_config_requirements()
        assert "username" in config
        assert config["username"]["description"] == "Username for basic authentication"
        assert config["username"]["depends_on"] == {"auth_type": "basic"}


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines: 207-210, 288-293, 346-347, 416-417, 620
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMCPToolTransportCreation:

    def test_unknown_transport_defaults_to_http(self, mcp_config):
        """Cover line 207-210 and 212: unknown transport type defaults to StreamableHttpTransport."""
        mcp_config["transport_type"] = "unknown_protocol"
        tool = _make_tool(mcp_config)
        transport = tool._create_transport()
        # Should be StreamableHttpTransport (the default fallback)
        assert transport is not None

    def test_sse_transport_creation(self, mcp_config):
        """Cover lines 201-203: SSE transport creation."""
        mcp_config["transport_type"] = "sse"
        tool = _make_tool(mcp_config)
        transport = tool._create_transport()
        assert transport is not None

    def test_stdio_transport_raises(self, mcp_config):
        """Cover line 200: stdio transport is disabled."""
        mcp_config["transport_type"] = "stdio"
        tool = _make_tool(mcp_config)
        with pytest.raises(ValueError, match="STDIO transport is disabled"):
            tool._create_transport()


@pytest.mark.unit
class TestMCPToolRunAsyncOperation:

    def test_run_async_operation_maps_error(self, mcp_config):
        """Cover lines 288-293: _run_async_operation exception mapped."""
        tool = _make_tool(mcp_config)

        async def bad_execute(op, *a, **kw):
            raise ConnectionRefusedError("refused")

        tool._execute_with_client = bad_execute
        tool._client = MagicMock()

        with pytest.raises(Exception, match="Connection refused"):
            tool._run_async_operation("ping")


@pytest.mark.unit
class TestMCPToolExecuteActionAuth:

    def test_execute_action_oauth_auth_error(self, mcp_config):
        """Cover lines 346-347: OAuth auth error raises specific message."""
        mcp_config["auth_type"] = "oauth"
        tool = _make_tool(mcp_config)

        def bad_run(*a, **kw):
            raise Exception("401 Unauthorized")

        tool._run_async_operation = bad_run
        tool._client = MagicMock()

        with pytest.raises(Exception, match="OAuth session expired"):
            tool.execute_action("test_action")


@pytest.mark.unit
class TestMCPToolTestConnectionInvalidScheme:

    def test_test_connection_ftp_scheme_invalid(self, mcp_config):
        """Cover lines 416-417: test_connection with invalid URL scheme."""
        tool = _make_tool(mcp_config)
        tool.server_url = "ftp://invalid.example.com"
        tool._client = None

        result = tool.test_connection()
        assert result["success"] is False
        assert "scheme" in result["message"].lower() or "Invalid" in result["message"]


@pytest.mark.unit
class TestMCPToolConfigRequirements:

    def test_get_config_requirements_has_password(self, mcp_config):
        """Cover line 620+: config requirements include password field."""
        tool = _make_tool(mcp_config)
        config = tool.get_config_requirements()
        assert "password" in config
        assert config["password"]["secret"] is True
        assert config["password"]["depends_on"] == {"auth_type": "basic"}


# ---------------------------------------------------------------------------
# Additional coverage for mcp_tool.py
# Lines: 207-210 (stdio transport), 288-293 (_map_error + _run_in_new_loop),
# 346-347 (execute_action error handling), 620 (config requirements password)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMCPToolStdioTransport:
    """Cover line 199-200: stdio transport raises ValueError."""

    def test_create_stdio_transport_raises(self, mcp_config):
        mcp_config["transport_type"] = "stdio"
        tool = _make_tool(mcp_config)
        tool.transport_type = "stdio"

        with pytest.raises(ValueError, match="STDIO transport is disabled"):
            tool._create_transport()

    def test_create_sse_transport(self, mcp_config):
        """Cover line 201-203: SSE transport."""
        mcp_config["transport_type"] = "sse"
        tool = _make_tool(mcp_config)
        tool.transport_type = "sse"
        transport = tool._create_transport()
        # Should return an SSETransport
        assert transport is not None

    def test_create_unknown_transport_defaults_to_http(self, mcp_config):
        """Cover line 211-212: unknown transport defaults to StreamableHttpTransport."""
        tool = _make_tool(mcp_config)
        tool.transport_type = "unknown_transport"
        transport = tool._create_transport()
        assert transport is not None


@pytest.mark.unit
class TestMCPToolRunInNewLoop:
    """Cover lines 288-293: _run_in_new_loop and _map_error."""

    def test_run_in_new_loop(self, mcp_config):
        tool = _make_tool(mcp_config)

        async def mock_execute(*args, **kwargs):
            return "loop_result"

        tool._execute_with_client = mock_execute
        result = tool._run_in_new_loop("list_tools")
        assert result == "loop_result"

    def test_map_error_timeout(self, mcp_config):
        tool = _make_tool(mcp_config)
        from asyncio import TimeoutError as AsyncTimeout

        err = tool._map_error("test_op", AsyncTimeout("timed out"))
        assert isinstance(err, Exception)
        assert "timeout" in str(err).lower() or "timed out" in str(err).lower()

    def test_map_error_generic(self, mcp_config):
        tool = _make_tool(mcp_config)
        err = tool._map_error("test_op", RuntimeError("something broke"))
        assert isinstance(err, Exception)


@pytest.mark.unit
class TestMCPToolExecuteActionErrorHandling:
    """Cover lines 346-347: execute_action non-auth error."""

    def test_execute_action_generic_error(self, mcp_config):
        tool = _make_tool(mcp_config)
        tool._run_async_operation = MagicMock(
            side_effect=RuntimeError("generic failure")
        )
        with pytest.raises(Exception, match="Failed to execute action"):
            tool.execute_action("some_action", key="value")
