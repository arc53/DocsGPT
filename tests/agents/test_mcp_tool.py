"""Tests for docsgpt/agents/tools/mcp_tool.py"""

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
    if "docsgpt.agents.tools.mcp_tool" in sys.modules:
        mcp_mod = sys.modules["docsgpt.agents.tools.mcp_tool"]
    else:
        # Break the circular import by pre-populating the tasks import
        # with a mock before mcp_tool tries to import it
        mock_tasks = MagicMock()
        monkeypatch.setitem(sys.modules, "docsgpt.api.user.tasks", mock_tasks)
        import docsgpt.agents.tools.mcp_tool as mcp_mod

    monkeypatch.setattr(mcp_mod, "_mcp_clients_cache", {})
    monkeypatch.setattr(mcp_mod, "validate_user_base_url", lambda url: None)


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
        from docsgpt.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client"):
            tool = MCPTool(mcp_config)

            assert tool.server_url == "https://mcp.example.com/api"
            assert tool.transport_type == "http"
            assert tool.auth_type == "none"
            assert tool.timeout == 10

    def test_bearer_auth_credentials(self, bearer_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client"):
            tool = MCPTool(bearer_config)
            assert tool.auth_credentials["bearer_token"] == "tok_123"

    def test_no_server_url_skips_setup(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            MCPTool({"server_url": "", "auth_type": "none"})
            mock_setup.assert_not_called()

    def test_oauth_skips_setup(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_none_auth(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        assert "none" in tool._cache_key
        assert "mcp.example.com" in tool._cache_key

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_bearer_auth(self, mock_setup, bearer_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(bearer_config)
        assert "bearer:" in tool._cache_key

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_api_key_auth(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "auth_type": "api_key",
                "auth_credentials": {"api_key": "sk-test12345678"},
            }
        )
        assert "apikey:" in tool._cache_key

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_basic_auth(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "auth_type": "basic",
                "auth_credentials": {"username": "user1", "password": "pass"},
            }
        )
        assert "basic:user1" in tool._cache_key

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_basic_auth_tells_passwords_apart(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        def key(password):
            return MCPTool(
                {
                    "server_url": "https://mcp.example.com",
                    "auth_type": "basic",
                    "auth_credentials": {"username": "user1", "password": password},
                }
            )._cache_key

        assert key("one") != key("two")
        assert key("one") == key("one")

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_a_secret_is_never_kept_in_the_key(self, mock_setup):
        from docsgpt.agents.tools import mcp_tool

        def key(token):
            return mcp_tool.MCPTool(
                {
                    "server_url": "https://mcp.example.com",
                    "auth_type": "bearer",
                    "auth_credentials": {"bearer_token": token},
                }
            )._cache_key

        first = key("github_pat_one")
        assert "github_pat" not in first
        assert first == key("github_pat_one")
        assert first != key("github_pat_two")
        assert not hasattr(mcp_tool, "_secret_tokens")


@pytest.mark.unit
class TestCreateTransport:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_http_transport(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        transport = tool._create_transport()
        assert transport is not None

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_sse_transport(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com/sse",
                "transport_type": "sse",
                "auth_type": "none",
            }
        )
        transport = tool._create_transport()
        assert transport is not None

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_auto_detects_sse(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com/sse",
                "transport_type": "auto",
                "auth_type": "none",
            }
        )
        transport = tool._create_transport()
        assert transport is not None

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_stdio_transport_disabled(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {
                "server_url": "https://mcp.example.com",
                "transport_type": "stdio",
                "auth_type": "none",
            }
        )
        with pytest.raises(ValueError, match="STDIO transport is disabled"):
            tool._create_transport()

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_api_key_header_injected(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_basic_auth_header_injected(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_list_of_dicts(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        result = tool._format_tools([{"name": "tool1", "description": "desc"}])
        assert len(result) == 1
        assert result[0]["name"] == "tool1"

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_tools_with_name_attribute(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.description = "A tool"
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        result = tool._format_tools([mock_tool])
        assert len(result) == 1
        assert result[0]["name"] == "my_tool"
        assert result[0]["inputSchema"] == {"type": "object", "properties": {}}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_tools_response_object(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        resp = MagicMock()
        resp.tools = [{"name": "t1", "description": "d1"}]

        result = tool._format_tools(resp)
        assert len(result) == 1

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_empty(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        assert tool._format_tools([]) == []
        assert tool._format_tools("unexpected") == []


@pytest.mark.unit
class TestFormatResult:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_result_with_content(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_raw_result(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        raw = {"key": "value"}
        assert tool._format_result(raw) == raw


@pytest.mark.unit
class TestExecuteAction:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_no_server_raises(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool({"server_url": "", "auth_type": "none"})
        with pytest.raises(Exception, match="No MCP server configured"):
            tool.execute_action("test_action")

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_successful_execute(self, mock_run, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = {"key": "value"}

        result = tool.execute_action("test_action", param1="val1")

        mock_run.assert_called_once_with("call_tool", "test_action", param1="val1")
        assert result == {"key": "value"}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_empty_kwargs_cleaned(self, mock_run, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_no_server_url(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool({"server_url": "", "auth_type": "none"})
        result = tool.test_connection()
        assert result["success"] is False
        assert "No server URL" in result["message"]

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_invalid_scheme(self, mock_setup):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(
            {"server_url": "ftp://bad.com", "auth_type": "none"}
        )
        result = tool.test_connection()
        assert result["success"] is False
        assert "Invalid URL scheme" in result["message"]


@pytest.mark.unit
class TestMapError:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_timeout_error(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool
        import concurrent.futures

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", concurrent.futures.TimeoutError())
        assert "Timed out" in str(err)

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_connection_refused(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", ConnectionRefusedError())
        assert "Connection refused" in str(err)

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_403_forbidden(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", Exception("403 Forbidden"))
        assert "Access denied" in str(err)

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_ssl_error(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        err = tool._map_error("test", Exception("SSL certificate verify failed"))
        assert "SSL" in str(err)

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_unknown_error_passthrough(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        original = RuntimeError("something weird")
        err = tool._map_error("test", original)
        assert err is original


@pytest.mark.unit
class TestGetActionsMetadata:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_empty_tools(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool.available_tools = []
        assert tool.get_actions_metadata() == []

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_tools_with_input_schema(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_tools_without_schema(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool.available_tools = [{"name": "ping", "description": "Ping"}]
        meta = tool.get_actions_metadata()
        assert meta[0]["parameters"]["properties"] == {}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_config_requirements(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        reqs = tool.get_config_requirements()
        assert "server_url" in reqs
        assert "auth_type" in reqs
        assert reqs["server_url"]["required"] is True


@pytest.mark.unit
class TestMCPOAuthManager:
    def test_handle_callback_success(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(state="abc123", code="auth_code")

        assert result is True
        mock_redis.setex.assert_called()

    def test_handle_callback_no_redis(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(None)
        result = manager.handle_oauth_callback(state="abc", code="code")
        assert result is False

    def test_handle_callback_error(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(
            state="abc", code="", error="access_denied"
        )
        assert result is False

    def test_get_oauth_status_no_task(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(MagicMock())
        result = manager.get_oauth_status("", "alice")
        assert result["status"] == "not_started"


@pytest.mark.skip(reason="DBTokenStorage signature changed post-PG migration; needs repo-based rewrite")
@pytest.mark.unit
class TestDBTokenStorage:
    def test_get_base_url(self):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        assert (
            DBTokenStorage.get_base_url("https://mcp.example.com/api/v1")
            == "https://mcp.example.com"
        )

    def test_get_db_key(self):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        mock_db = MagicMock()
        storage = DBTokenStorage(
            server_url="https://mcp.example.com/api",
            user_id="user1",
            db_client=mock_db,
        )
        key = storage.get_db_key()
        assert key["server_url"] == "https://mcp.example.com"
        assert key["user_id"] == "user1"


@pytest.mark.unit
class TestMcpAppsMetadata:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_format_tools_keeps_ui_metadata(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        listed = MagicMock()
        listed.name = "create_view"
        listed.description = "Draw"
        listed.inputSchema = {"type": "object", "properties": {}}
        listed.annotations = None
        listed.meta = {"ui": {"resourceUri": "ui://excalidraw/mcp-app.html"}, "ui/resourceUri": "ui://excalidraw/mcp-app.html"}
        app_only = MagicMock()
        app_only.name = "save_checkpoint"
        app_only.description = "Save"
        app_only.inputSchema = {"type": "object", "properties": {}}
        app_only.annotations = None
        app_only.meta = {"ui": {"visibility": ["app"]}}

        formatted = tool._format_tools([listed, app_only])
        assert formatted[0]["ui"] == {"resourceUri": "ui://excalidraw/mcp-app.html"}
        assert formatted[1]["ui"] == {"visibility": ["app"]}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_actions_metadata_carries_ui(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool.available_tools = [
            {"name": "create_view", "description": "", "ui": {"resourceUri": "ui://a/b.html"}},
            {"name": "read_me", "description": "", "_meta": {"ui": {"visibility": ["model"]}}},
            {"name": "plain", "description": ""},
        ]
        actions = {a["name"]: a for a in tool.get_actions_metadata()}
        assert actions["create_view"]["ui"] == {"resourceUri": "ui://a/b.html"}
        assert actions["read_me"]["ui"] == {"visibility": ["model"]}
        assert "ui" not in actions["plain"]


@pytest.mark.unit
class TestMcpAppsResource:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_reads_and_caches_the_view(self, mock_setup, mcp_config):
        from mcp.types import TextResourceContents

        from docsgpt.agents.tools import mcp_tool as module
        from docsgpt.agents.tools.mcp_tool import MCPTool

        module._ui_resource_cache.clear()
        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        contents = [
            TextResourceContents(
                uri="ui://excalidraw/mcp-app.html",
                mime_type="text/html;profile=mcp-app",
                text="<html>app</html>",
                _meta={"ui": {"csp": {"connectDomains": ["https://esm.sh"]}, "permissions": {"clipboardWrite": {}}}},
            )
        ]
        with patch.object(MCPTool, "_run_async_operation", return_value=contents) as run:
            first = tool.read_ui_resource("ui://excalidraw/mcp-app.html")
            second = tool.read_ui_resource("ui://excalidraw/mcp-app.html")
        assert first == second
        assert first["html"] == "<html>app</html>"
        assert first["csp"] == {"connectDomains": ["https://esm.sh"]}
        assert first["permissions"] == {"clipboardWrite": {}}
        run.assert_called_once_with("read_resource", "ui://excalidraw/mcp-app.html")

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_falls_back_to_the_listing_meta(self, mock_setup, mcp_config):
        from mcp.types import Resource, TextResourceContents

        from docsgpt.agents.tools import mcp_tool as module
        from docsgpt.agents.tools.mcp_tool import MCPTool

        module._ui_resource_cache.clear()
        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        contents = [TextResourceContents(uri="ui://a/b.html", mime_type="text/html;profile=mcp-app", text="<p>")]
        listing = [Resource(uri="ui://a/b.html", name="b", _meta={"ui": {"prefersBorder": False}})]

        def run(operation, *args, **kwargs):
            return contents if operation == "read_resource" else listing

        with patch.object(MCPTool, "_run_async_operation", side_effect=run):
            view = tool.read_ui_resource("ui://a/b.html")
        assert view == {"html": "<p>", "prefersBorder": False}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_reads_the_listing_when_the_view_item_declares_no_ui(self, mock_setup, mcp_config):
        # Other ``_meta`` on the item is no reason to skip the listing's CSP.
        from mcp.types import Resource, TextResourceContents

        from docsgpt.agents.tools import mcp_tool as module
        from docsgpt.agents.tools.mcp_tool import MCPTool

        module._ui_resource_cache.clear()
        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        contents = [
            TextResourceContents(
                uri="ui://a/b.html", mime_type="text/html;profile=mcp-app", text="<p>", _meta={"other": 1}
            )
        ]
        listing = [Resource(uri="ui://a/b.html", name="b", _meta={"ui": {"csp": {"connectDomains": ["https://x.io"]}}})]

        def run(operation, *args, **kwargs):
            return contents if operation == "read_resource" else listing

        with patch.object(MCPTool, "_run_async_operation", side_effect=run):
            view = tool.read_ui_resource("ui://a/b.html")
        assert view["csp"] == {"connectDomains": ["https://x.io"]}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_skips_the_listing_when_the_view_item_declares_its_ui(self, mock_setup, mcp_config):
        from mcp.types import TextResourceContents

        from docsgpt.agents.tools import mcp_tool as module
        from docsgpt.agents.tools.mcp_tool import MCPTool

        module._ui_resource_cache.clear()
        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        contents = [
            TextResourceContents(
                uri="ui://a/b.html", mime_type="text/html;profile=mcp-app", text="<p>",
                _meta={"ui": {"prefersBorder": True}},
            )
        ]
        with patch.object(MCPTool, "_run_async_operation", return_value=contents) as run:
            tool.read_ui_resource("ui://a/b.html")
        run.assert_called_once_with("read_resource", "ui://a/b.html")

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_an_entry_another_request_evicted_first_does_not_fail_the_read(self, mock_setup, mcp_config, monkeypatch):
        from mcp.types import TextResourceContents

        from docsgpt.agents.tools import mcp_tool as module
        from docsgpt.agents.tools.mcp_tool import MCPTool

        class Raced(dict):
            """The oldest entry is gone by the time this request pops it."""

            def pop(self, key, *default):
                if not default:
                    raise KeyError(key)
                return super().pop(key, *default)

        cache = Raced({(f"k{i}", "ui://x"): (0, {}) for i in range(module.UI_RESOURCE_CACHE_SIZE)})
        monkeypatch.setattr(module, "_ui_resource_cache", cache)
        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        contents = [TextResourceContents(uri="ui://a/b.html", mime_type="text/html;profile=mcp-app", text="<p>",
                                         _meta={"ui": {}})]
        with patch.object(MCPTool, "_run_async_operation", return_value=contents):
            assert tool.read_ui_resource("ui://a/b.html")["html"] == "<p>"
        assert len(cache) == module.UI_RESOURCE_CACHE_SIZE

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_refuses_other_schemes(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        with pytest.raises(ValueError):
            MCPTool(mcp_config).read_ui_resource("https://example.com/app.html")


@pytest.mark.unit
class TestMcpAppsResults:
    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_execute_keeps_the_typed_result_for_the_view(self, mock_setup, mcp_config):
        from fastmcp.client.client import CallToolResult
        from mcp.types import TextContent

        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        result = CallToolResult(
            content=[TextContent(type="text", text="Diagram displayed!")],
            structured_content={"checkpointId": "abc"},
            meta=None,
        )
        with patch.object(MCPTool, "_run_async_operation", return_value=result):
            model_copy = tool.execute_action("create_view", elements="[]")
        assert model_copy["content"] == [{"type": "text", "text": "Diagram displayed!"}]
        assert tool.take_app_result() == {
            "content": [{"type": "text", "text": "Diagram displayed!"}],
            "structuredContent": {"checkpointId": "abc"},
            "isError": False,
        }
        assert tool.take_app_result() is None

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_app_call_returns_errors_in_band(self, mock_setup, mcp_config):
        from fastmcp.client.client import CallToolResult
        from mcp.types import TextContent

        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        result = CallToolResult(
            content=[TextContent(type="text", text="no such checkpoint")], structured_content=None, meta=None,
            is_error=True,
        )
        with patch.object(MCPTool, "_run_async_operation", return_value=result) as run:
            answer = tool.call_app_tool("read_checkpoint", {"id": "x"})
        run.assert_called_once_with("call_tool_raw", "read_checkpoint", {"id": "x"})
        assert answer == {"content": [{"type": "text", "text": "no such checkpoint"}], "isError": True}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_app_call_retries_with_listed_schemas_after_a_header_mismatch(self, mock_setup, mcp_config):
        from fastmcp.client.client import CallToolResult
        from mcp.shared.exceptions import MCPError
        from mcp.types import HEADER_MISMATCH, TextContent

        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        result = CallToolResult(content=[TextContent(type="text", text="ok")], structured_content=None, meta=None)
        calls = []

        def run(operation, *args, **kwargs):
            calls.append(operation)
            if operation == "call_tool_raw" and calls.count("call_tool_raw") == 1:
                raise MCPError(HEADER_MISMATCH, "missing Mcp-Param-repo")
            return [] if operation == "list_tools" else result

        with patch.object(MCPTool, "_run_async_operation", side_effect=run):
            answer = tool.call_app_tool("read_checkpoint", {"id": "x"})
        assert calls == ["call_tool_raw", "list_tools", "call_tool_raw"]
        assert answer["content"] == [{"type": "text", "text": "ok"}]

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._setup_client")
    def test_app_call_does_not_retry_other_failures(self, mock_setup, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = MCPTool(mcp_config)
        tool._client = MagicMock()
        with patch.object(MCPTool, "_run_async_operation", side_effect=Exception("boom")) as run:
            with pytest.raises(Exception, match="boom"):
                tool.call_app_tool("save_checkpoint", {"id": "x"})
        run.assert_called_once()
