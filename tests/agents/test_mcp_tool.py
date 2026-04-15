"""Tests for application/agents/tools/mcp_tool.py"""

from unittest.mock import MagicMock, patch

import pytest


# mcp_tool has a circular import at module level (mcp_tool -> tasks -> user -> mcp.py -> mcp_tool).
# We must patch the dependencies BEFORE the module is first imported.
@pytest.fixture(autouse=True)
def _patch_mcp_globals(monkeypatch):
    """Patch module-level cache to avoid real connections.

    MongoDB is no longer used at module level; DBTokenStorage now backs
    onto the ``connector_sessions`` Postgres repository. The cache patch
    is still required to avoid hitting real Redis.
    """
    import sys

    # If the module is already loaded, just patch attributes directly
    if "application.agents.tools.mcp_tool" in sys.modules:
        mcp_mod = sys.modules["application.agents.tools.mcp_tool"]
    else:
        # Break the circular import by pre-populating the tasks import
        # with a mock before mcp_tool tries to import it
        mock_tasks = MagicMock()
        monkeypatch.setitem(sys.modules, "application.api.user.tasks", mock_tasks)
        import application.agents.tools.mcp_tool as mcp_mod

    mock_mongo = MagicMock()
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(mcp_mod, "mongo", mock_mongo)
    monkeypatch.setattr(mcp_mod, "db", mock_db)
    monkeypatch.setattr(mcp_mod, "_mcp_clients_cache", {})
    monkeypatch.setattr(mcp_mod, "validate_url", lambda url: url)


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


@pytest.mark.unit
class TestMCPToolInit:
    def test_basic_init(self, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client"):
            tool = MCPTool(mcp_config)

            assert tool.server_url == "https://mcp.example.com/api"
            assert tool.transport_type == "http"
            assert tool.auth_type == "none"
            assert tool.timeout == 10

    def test_bearer_auth_credentials(self, bearer_config):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client"):
            tool = MCPTool(bearer_config)
            assert tool.auth_credentials["bearer_token"] == "tok_123"

    def test_no_server_url_skips_setup(self):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            MCPTool({"server_url": "", "auth_type": "none"})
            mock_setup.assert_not_called()

    def test_oauth_skips_setup(self):
        from application.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            MCPTool(
                {
                    "server_url": "https://mcp.example.com",
                    "auth_type": "oauth",
                }
            )
            mock_setup.assert_not_called()


@pytest.mark.unit
class TestGenerateCacheKey:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_none_auth(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        assert "none" in tool._cache_key
        assert "mcp.example.com" in tool._cache_key

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_bearer_auth(self, mock_setup, bearer_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(bearer_config)
        assert "bearer:" in tool._cache_key

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_api_key_auth(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "auth_type": "api_key",
                "auth_credentials": {"api_key": "sk-test12345678"},
            }
        )
        assert "apikey:" in tool._cache_key

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_basic_auth(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "auth_type": "basic",
                "auth_credentials": {"username": "user1", "password": "pass"},
            }
        )
        assert "basic:user1" in tool._cache_key


@pytest.mark.unit
class TestCreateTransport:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_http_transport(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        transport = tool._create_transport()
        assert transport is not None

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_sse_transport(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com/sse",
                "transport_type": "sse",
                "auth_type": "none",
            }
        )
        transport = tool._create_transport()
        assert transport is not None

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_auto_detects_sse(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com/sse",
                "transport_type": "auto",
                "auth_type": "none",
            }
        )
        transport = tool._create_transport()
        assert transport is not None

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_stdio_transport_disabled(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "transport_type": "stdio",
                "auth_type": "none",
            }
        )
        with pytest.raises(ValueError, match="STDIO transport is disabled"):
            tool._create_transport()

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_api_key_header_injected(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "transport_type": "http",
                "auth_type": "api_key",
                "auth_credentials": {
                    "api_key": "sk-test",
                    "api_key_header": "X-Custom-Key",
                },
            }
        )
        # _create_transport will be called; verify it doesn't raise
        transport = tool._create_transport()
        assert transport is not None

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_basic_auth_header_injected(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "transport_type": "http",
                "auth_type": "basic",
                "auth_credentials": {"username": "user", "password": "pass"},
            }
        )
        transport = tool._create_transport()
        assert transport is not None


@pytest.mark.unit
class TestFormatTools:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_list_of_dicts(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        result = tool._format_tools([{"name": "tool1", "description": "desc"}])
        assert len(result) == 1
        assert result[0]["name"] == "tool1"

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_tools_with_name_attribute(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.description = "A tool"
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        result = tool._format_tools([mock_tool])
        assert len(result) == 1
        assert result[0]["name"] == "my_tool"
        assert result[0]["inputSchema"] == {"type": "object", "properties": {}}

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_tools_response_object(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        resp = MagicMock()
        resp.tools = [{"name": "t1", "description": "d1"}]

        result = tool._format_tools(resp)
        assert len(result) == 1

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_empty(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        assert tool._format_tools([]) == []
        assert tool._format_tools("unexpected") == []


@pytest.mark.unit
class TestFormatResult:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_result_with_content(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
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

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_raw_result(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        raw = {"key": "value"}
        assert tool._format_result(raw) == raw


@pytest.mark.unit
class TestExecuteAction:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_no_server_raises(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool({"server_url": "", "auth_type": "none"})
        with pytest.raises(Exception, match="No MCP server configured"):
            tool.execute_action("test_action")

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_successful_execute(self, mock_run, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = {"key": "value"}

        result = tool.execute_action("test_action", param1="val1")

        mock_run.assert_called_once_with("call_tool", "test_action", param1="val1")
        assert result == {"key": "value"}

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    @patch("application.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_empty_kwargs_cleaned(self, mock_run, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = {}

        tool.execute_action("test", param1="", param2=None, param3="real")

        call_kwargs = mock_run.call_args[1]
        assert "param1" not in call_kwargs
        assert "param2" not in call_kwargs
        assert call_kwargs["param3"] == "real"


@pytest.mark.unit
class TestTestConnection:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_no_server_url(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool({"server_url": "", "auth_type": "none"})
        result = tool.test_connection()
        assert result["success"] is False
        assert "No server URL" in result["message"]

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_invalid_scheme(self, mock_setup):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {"server_url": "ftp://bad.com", "auth_type": "none"}
        )
        result = tool.test_connection()
        assert result["success"] is False
        assert "Invalid URL scheme" in result["message"]


@pytest.mark.unit
class TestMapError:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_timeout_error(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool
        import concurrent.futures

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", concurrent.futures.TimeoutError())
        assert "Timed out" in str(err)

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_connection_refused(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", ConnectionRefusedError())
        assert "Connection refused" in str(err)

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_403_forbidden(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", Exception("403 Forbidden"))
        assert "Access denied" in str(err)

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_ssl_error(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", Exception("SSL certificate verify failed"))
        assert "SSL" in str(err)

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_unknown_error_passthrough(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        original = RuntimeError("something weird")
        err = tool._map_error("test", original)
        assert err is original


@pytest.mark.unit
class TestGetActionsMetadata:
    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_empty_tools(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool.available_tools = []
        assert tool.get_actions_metadata() == []

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_tools_with_input_schema(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool.available_tools = [
            {
                "name": "search",
                "description": "Search things",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ]
        meta = tool.get_actions_metadata()
        assert len(meta) == 1
        assert meta[0]["name"] == "search"
        assert "query" in meta[0]["parameters"]["properties"]

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_tools_without_schema(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool.available_tools = [{"name": "ping", "description": "Ping"}]
        meta = tool.get_actions_metadata()
        assert meta[0]["parameters"]["properties"] == {}

    @patch("application.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_config_requirements(self, mock_setup, mcp_config):
        from application.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        reqs = tool.get_config_requirements()
        assert "server_url" in reqs
        assert "auth_type" in reqs
        assert reqs["server_url"]["required"] is True


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


@pytest.mark.unit
class TestDBTokenStorage:
    def test_get_base_url(self):
        from application.agents.tools.mcp_tool import DBTokenStorage

        assert (
            DBTokenStorage.get_base_url("https://mcp.example.com/api/v1")
            == "https://mcp.example.com"
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
