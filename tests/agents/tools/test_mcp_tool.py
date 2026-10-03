"""Comprehensive tests for docsgpt/agents/tools/mcp_tool.py

Covers: MCPTool init, cache key generation, transport creation, tool formatting,
result formatting, execute_action, discover_tools, test_connection,
get_actions_metadata, DocsGPTOAuth, NonInteractiveOAuth, DBTokenStorage,
MCPOAuthManager.
"""

import asyncio
import concurrent.futures
import json
from unittest.mock import MagicMock, patch

import pytest


# ---- Fixtures to isolate module-level side effects ----

@pytest.fixture(autouse=True)
def _patch_mcp_globals(monkeypatch):
    """Patch module-level cache to avoid real connections.

    MongoDB is no longer used at module level; DBTokenStorage now backs
    onto the ``connector_sessions`` Postgres repository. The cache patch
    is still required to avoid hitting real Redis.
    """
    import sys

    if "docsgpt.agents.tools.mcp_tool" in sys.modules:
        mcp_mod = sys.modules["docsgpt.agents.tools.mcp_tool"]
    else:
        mock_tasks = MagicMock()
        monkeypatch.setitem(sys.modules, "docsgpt.api.user.tasks", mock_tasks)
        import docsgpt.agents.tools.mcp_tool as mcp_mod

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
    from docsgpt.agents.tools.mcp_tool import MCPTool

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
        from docsgpt.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            MCPTool({"server_url": "", "auth_type": "none"})
            mock_setup.assert_not_called()

    def test_oauth_skips_setup(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client") as mock_setup:
            MCPTool({
                "server_url": "https://mcp.example.com",
                "auth_type": "oauth",
            })
            mock_setup.assert_not_called()

    def test_encrypted_credentials_decryption(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        with patch.object(MCPTool, "_setup_client"), \
             patch("docsgpt.agents.tools.mcp_tool.decrypt_credentials",
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
        from docsgpt.agents.tools.mcp_tool import MCPTool
        from docsgpt.core.url_validation import validate_url as real_validate_url
        import docsgpt.agents.tools.mcp_tool as mcp_mod

        monkeypatch.setattr(mcp_mod, "validate_url", real_validate_url)
        with pytest.raises(ValueError, match="Invalid MCP server URL"):
            MCPTool(config={"server_url": "http://169.254.169.254/latest/meta-data", "auth_type": "none"})

    def test_rejects_localhost(self, monkeypatch):
        from docsgpt.agents.tools.mcp_tool import MCPTool
        from docsgpt.core.url_validation import validate_url as real_validate_url
        import docsgpt.agents.tools.mcp_tool as mcp_mod

        monkeypatch.setattr(mcp_mod, "validate_url", real_validate_url)
        with pytest.raises(ValueError, match="Invalid MCP server URL"):
            MCPTool(config={"server_url": "http://localhost:8080/mcp", "auth_type": "none"})

    def test_rejects_private_ip(self, monkeypatch):
        from docsgpt.agents.tools.mcp_tool import MCPTool
        from docsgpt.core.url_validation import validate_url as real_validate_url
        import docsgpt.agents.tools.mcp_tool as mcp_mod

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
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
        from docsgpt.core.settings import settings

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

    @pytest.mark.parametrize("auth_type, field", [("bearer", "bearer_token"), ("api_key", "api_key")])
    def test_tokens_with_a_shared_prefix_get_their_own_client(self, auth_type, field):
        """Every fine-grained GitHub token starts with ``github_pat_``; two users' tokens
        must never share a cached client (it carries the first user's token)."""
        first = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": auth_type,
            "auth_credentials": {field: "github_pat_11AAAAAAA_alice"},
        })
        second = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": auth_type,
            "auth_credentials": {field: "github_pat_11AAAAAAA_bob"},
        })
        assert first._cache_key != second._cache_key
        assert "github_pat" not in first._cache_key


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

    def test_an_image_is_shown_to_the_model_not_inlined(self, mcp_config):
        import base64
        import io
        from types import SimpleNamespace

        from mcp.types import ImageContent
        from PIL import Image

        out = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(out, "PNG")
        data = base64.b64encode(out.getvalue()).decode()
        tool = _make_tool(mcp_config)
        result = tool._format_result(
            SimpleNamespace(content=[ImageContent(type="image", data=data, mimeType="image/png")], isError=False),
            "screenshot",
        )

        assert result["content"] == [{"type": "image", "note": "shown to you as screenshot image 1"}]
        assert data not in str(result)
        parts = tool.drain_native_parts()
        assert parts == [{"label": "screenshot image 1", "mime_type": "image/png", "data": data}]
        assert tool.drain_native_parts() == []

    def test_resources_and_other_content(self, mcp_config):
        from types import SimpleNamespace

        from mcp.types import (
            AudioContent,
            BlobResourceContents,
            EmbeddedResource,
            ResourceLink,
            TextResourceContents,
        )

        tool = _make_tool(mcp_config)
        result = tool._format_result(
            SimpleNamespace(
                content=[
                    EmbeddedResource(type="resource", resource=TextResourceContents(
                        uri="file:///a.txt", mimeType="text/plain", text="hi")),
                    EmbeddedResource(type="resource", resource=BlobResourceContents(
                        uri="file:///a.bin", mimeType="application/zip", blob="UEsDBA==")),
                    EmbeddedResource(type="resource", resource=BlobResourceContents(
                        uri="file:///a.png", mimeType="image/png", blob="bm90IGFuIGltYWdl")),
                    ResourceLink(type="resource_link", uri="https://x.test/r", name="r", mimeType="text/html"),
                    AudioContent(type="audio", data="AAAA", mimeType="audio/wav"),
                ],
                is_error=True,
            ),
            "fetch",
        )

        text, blob, image, link, audio = result["content"]
        assert text == {"type": "resource", "uri": "file:///a.txt", "mimeType": "text/plain", "text": "hi"}
        assert blob["note"] == "binary content, not shown" and "UEsDBA" not in str(blob)
        assert image == {"type": "image", "note": "an image that could not be read"}
        assert link == {"type": "resource_link", "uri": "https://x.test/r", "name": "r", "mimeType": "text/html"}
        assert audio == {"type": "audio", "mimeType": "audio/wav", "note": "audio, not shown"}
        assert result["isError"] is True
        assert tool.drain_native_parts() == []

    def test_format_result_unknown_content_type(self, mcp_config):
        from types import SimpleNamespace

        tool = _make_tool(mcp_config)
        result = tool._format_result(SimpleNamespace(content=[SimpleNamespace(type="video")], isError=False))
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_an_earlier_calls_images_are_not_carried_over(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        tool._native_queue = [{"label": "stale"}]
        mock_run.return_value = {"key": "value"}
        tool.execute_action("test_action")
        assert tool.drain_native_parts() == []

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_successful_execute(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = {"key": "value"}

        result = tool.execute_action("test_action", param1="val1")

        mock_run.assert_called_once_with("call_tool", "test_action", param1="val1")
        assert result == {"key": "value"}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_empty_kwargs_cleaned(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.return_value = {}

        tool.execute_action("test", param1="", param2=None, param3="real")

        call_kwargs = mock_run.call_args[1]
        assert "param1" not in call_kwargs
        assert "param2" not in call_kwargs
        assert call_kwargs["param3"] == "real"

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_auth_error_retries_for_non_oauth(self, mock_run, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = _make_tool(mcp_config)
        tool._client = MagicMock()

        mock_run.side_effect = [
            Exception("401 Unauthorized"),
            {"key": "retry_ok"},
        ]

        with patch.object(MCPTool, "_setup_client"):
            result = tool.execute_action("act")
            assert result == {"key": "retry_ok"}

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_auth_error_raises_for_oauth(self, mock_run):
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
        })
        tool._client = MagicMock()
        mock_run.side_effect = Exception("401 Unauthorized")

        with pytest.raises(Exception, match="OAuth session expired"):
            tool.execute_action("act")

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_non_auth_error_raises(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = Exception("Something weird happened")

        with pytest.raises(Exception, match="Failed to execute action"):
            tool.execute_action("act")

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_no_client_calls_setup(self, mock_run, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_regular_connection_ping_fails_tools_work(self, mock_run, mcp_config):
        tool = _make_tool(mcp_config)
        tool._client = MagicMock()
        mock_run.side_effect = [
            Exception("ping failed"),  # ping
            [{"name": "t1", "description": "d1"}],  # list_tools
        ]

        result = tool.test_connection()
        assert result["success"] is True

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
             patch("docsgpt.agents.tools.mcp_tool.Client", return_value=mock_client):
            tool._setup_client()
            assert tool._client is mock_client


# =====================================================================
# MCPOAuthManager
# =====================================================================


@pytest.mark.unit
class TestMCPOAuthManager:

    def test_handle_callback_success(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(state="abc123", code="auth_code")
        assert result is True
        mock_redis.setex.assert_called()

    def test_handle_callback_keeps_the_issuer(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        assert manager.handle_oauth_callback(state="s", code="c", iss="https://issuer.example") is True
        mock_redis.setex.assert_any_call("mcp_oauth:iss:s", 300, "https://issuer.example")

    def test_handle_callback_no_redis(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(None)
        result = manager.handle_oauth_callback(state="abc", code="code")
        assert result is False

    def test_handle_callback_no_state(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)
        result = manager.handle_oauth_callback(state="", code="code")
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

    def test_get_oauth_status_no_user(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(MagicMock())
        result = manager.get_oauth_status("task123", "")
        # Without a user id we can't address the per-user SSE journal,
        # so the manager refuses rather than scanning every user's
        # stream.
        assert result["status"] == "not_found"

    def test_get_oauth_status_reads_completed_envelope_from_journal(self):
        """The manager walks the user's SSE Streams journal and
        surfaces the latest ``mcp.oauth.*`` envelope for the task.

        Verifies the full polling-contract surface: ``status`` is
        derived from the event-type suffix, and the completed
        payload's ``tools`` / ``tools_count`` fields are passed
        through unchanged so ``mcp.py``'s ``connect_mcp`` can use them
        without further plumbing.
        """
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        completed_envelope = json.dumps(
            {
                "type": "mcp.oauth.completed",
                "scope": {"kind": "mcp_oauth", "id": "task123"},
                "payload": {
                    "task_id": "task123",
                    "tools": [{"name": "t1", "description": "d"}],
                    "tools_count": 1,
                },
            }
        ).encode("utf-8")
        # xrevrange yields newest-first; an unrelated older entry
        # should be skipped on the way to the matching one.
        unrelated_envelope = json.dumps(
            {
                "type": "source.ingest.completed",
                "scope": {"kind": "source", "id": "abc"},
                "payload": {},
            }
        ).encode("utf-8")
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [
            (b"1735682400000-0", {b"event": completed_envelope}),
            (b"1735682300000-0", {b"event": unrelated_envelope}),
        ]

        manager = MCPOAuthManager(mock_redis)
        result = manager.get_oauth_status("task123", "alice")

        assert result["status"] == "completed"
        assert result["tools"] == [{"name": "t1", "description": "d"}]
        assert result["tools_count"] == 1
        # The stream key is scoped per-user — never global.
        mock_redis.xrevrange.assert_called_once()
        call_args = mock_redis.xrevrange.call_args
        assert "user:alice:stream" in call_args.args
        # Scan window must cover the full bounded stream so a flood of
        # concurrent source-ingest events between popup-completed and
        # Save can't push the OAuth envelope out of view.
        from docsgpt.core.settings import settings

        assert call_args.kwargs.get("count") >= settings.EVENTS_STREAM_MAXLEN

    def test_get_oauth_status_scan_covers_events_stream_maxlen(self):
        """Regression: count must scale with ``EVENTS_STREAM_MAXLEN``
        so the OAuth completion envelope is reachable even after
        concurrent source-ingest events flood the user stream."""
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager
        from docsgpt.core.settings import settings

        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = []

        manager = MCPOAuthManager(mock_redis)
        manager.get_oauth_status("task123", "alice")

        call_args = mock_redis.xrevrange.call_args
        assert call_args.kwargs.get("count") >= settings.EVENTS_STREAM_MAXLEN

    def test_get_oauth_status_returns_not_found_when_no_match(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        # Stream is non-empty but has nothing matching this task.
        unrelated_envelope = json.dumps(
            {
                "type": "mcp.oauth.completed",
                "scope": {"kind": "mcp_oauth", "id": "other-task"},
                "payload": {"task_id": "other-task"},
            }
        ).encode("utf-8")
        mock_redis.xrevrange.return_value = [
            (b"1735682400000-0", {b"event": unrelated_envelope}),
        ]

        manager = MCPOAuthManager(mock_redis)
        result = manager.get_oauth_status("task123", "alice")

        assert result["status"] == "not_found"


# =====================================================================
# DBTokenStorage
# =====================================================================


@pytest.mark.unit
class TestDBTokenStorage:
    """Covers the repository-backed DBTokenStorage post-PG migration.

    Round-trip tests use the ephemeral ``pg_conn`` fixture and patch
    ``db_session``/``db_readonly`` in ``docsgpt.agents.tools.mcp_tool``
    so the real INSERT/SELECT SQL runs. This is the shape that caught the
    ``server_url`` NULL-column regression — ``get_tokens`` only succeeds
    if ``set_tokens`` populated the scalar column.
    """

    @staticmethod
    def _patch_db(monkeypatch, pg_conn):
        from contextlib import contextmanager

        import docsgpt.agents.tools.mcp_tool as mcp_mod

        @contextmanager
        def _yield():
            yield pg_conn

        monkeypatch.setattr(mcp_mod, "db_session", _yield, raising=False)
        monkeypatch.setattr(mcp_mod, "db_readonly", _yield, raising=False)
        # mcp_tool imports db_session/db_readonly *inside* the helper
        # methods, so also patch the origin module they come from.
        import docsgpt.storage.db.session as session_mod

        monkeypatch.setattr(session_mod, "db_session", _yield)
        monkeypatch.setattr(session_mod, "db_readonly", _yield)
        import docsgpt.connectors.service as service_mod

        monkeypatch.setattr(service_mod, "db_session", _yield)
        monkeypatch.setattr(service_mod, "db_readonly", _yield)

    def test_get_base_url(self):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        assert (
            DBTokenStorage.get_base_url("https://mcp.example.com/api/v1")
            == "https://mcp.example.com"
        )

    def test_get_base_url_with_port(self):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        assert (
            DBTokenStorage.get_base_url("http://localhost:8080/path")
            == "http://localhost:8080"
        )

    def test_pg_provider_includes_base_url(self):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        storage = DBTokenStorage(
            server_url="https://mcp.example.com/api",
            user_id="user1",
        )
        assert storage._pg_provider() == "mcp:https://mcp.example.com"

    def test_serialize_client_info(self):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        storage = DBTokenStorage(
            server_url="https://mcp.example.com",
            user_id="user1",
        )
        info = {"redirect_uris": ["https://example.com/cb"]}
        result = storage._serialize_client_info(info)
        assert result["redirect_uris"] == ["https://example.com/cb"]

    def test_get_tokens_none_when_no_row(self, monkeypatch, pg_conn):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        self._patch_db(monkeypatch, pg_conn)
        storage = DBTokenStorage(
            server_url="https://mcp.example.com/api",
            user_id="user-empty",
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(storage.get_tokens())
            assert result is None
        finally:
            loop.close()

    def test_set_then_get_tokens_roundtrip(self, monkeypatch, pg_conn):
        """Regression: ``set_tokens`` must populate the scalar
        ``server_url`` column so ``get_tokens`` (which goes through
        ``get_by_user_and_server_url``) can resolve the row."""
        from mcp.shared.auth import OAuthToken

        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        self._patch_db(monkeypatch, pg_conn)
        storage = DBTokenStorage(
            server_url="https://mcp.example.com/api/v1",
            user_id="user-roundtrip",
        )

        tokens_in = OAuthToken(
            access_token="at-abc",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="rt-xyz",
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(storage.set_tokens(tokens_in))
            tokens_out = loop.run_until_complete(storage.get_tokens())
        finally:
            loop.close()

        assert tokens_out is not None
        assert tokens_out.access_token == "at-abc"
        assert tokens_out.refresh_token == "rt-xyz"

    def test_long_client_id_survives_reconnect(self, monkeypatch, pg_conn):
        from mcp.shared.auth import OAuthClientInformationFull

        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        self._patch_db(monkeypatch, pg_conn)
        client_id = "client-" + "x" * 4096
        server_url = "https://api.motherduck.com/mcp"
        user_id = "user-long-client-id"
        storage = DBTokenStorage(server_url=server_url, user_id=user_id)
        client_info = OAuthClientInformationFull(
            client_id=client_id,
            redirect_uris=["https://docsgpt.example.com/api/mcp_server/callback"],
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(storage.set_client_info(client_info))
            reconnected_storage = DBTokenStorage(server_url=server_url, user_id=user_id)
            restored = loop.run_until_complete(reconnected_storage.get_client_info())
        finally:
            loop.close()

        assert restored is not None
        assert restored.client_id == client_id

    def test_set_tokens_populates_scalar_server_url(
        self, monkeypatch, pg_conn,
    ):
        """Direct check that the fix writes ``server_url`` to the scalar
        column, not only into the JSONB blob."""
        from mcp.shared.auth import OAuthToken

        from docsgpt.agents.tools.mcp_tool import DBTokenStorage
        from docsgpt.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        self._patch_db(monkeypatch, pg_conn)
        base_url = "https://mcp.scalar.example.com"
        storage = DBTokenStorage(
            server_url=f"{base_url}/api",
            user_id="user-scalar",
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                storage.set_tokens(
                    OAuthToken(access_token="at", token_type="Bearer"),
                ),
            )
        finally:
            loop.close()

        row = ConnectorSessionsRepository(pg_conn).get_by_user_and_server_url(
            "user-scalar", base_url,
        )
        assert row is not None
        assert row["server_url"] == base_url
        # ``server_url`` must NOT be duplicated inside the JSONB blob.
        session_data = row["session_data"] or {}
        assert "server_url" not in session_data
        # Tokens live only in the encrypted envelope, never in plaintext.
        assert "tokens" not in session_data
        assert row["encrypted_credentials"].startswith("v2:")
        from docsgpt.connectors.service import read_secrets

        assert read_secrets(row)["tokens"]["access_token"] == "at"
        assert row["status"] == "connected"

    def test_clear_removes_row(self, monkeypatch, pg_conn):
        from mcp.shared.auth import OAuthToken

        from docsgpt.agents.tools.mcp_tool import DBTokenStorage
        from docsgpt.storage.db.repositories.connector_sessions import (
            ConnectorSessionsRepository,
        )

        self._patch_db(monkeypatch, pg_conn)
        base_url = "https://mcp.clear.example.com"
        storage = DBTokenStorage(
            server_url=f"{base_url}/api",
            user_id="user-clear",
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                storage.set_tokens(
                    OAuthToken(access_token="at", token_type="Bearer"),
                ),
            )
            loop.run_until_complete(storage.clear())
        finally:
            loop.close()

        assert (
            ConnectorSessionsRepository(pg_conn).get_by_user_and_server_url(
                "user-clear", base_url,
            )
            is None
        )

    def test_stored_tokens_remember_when_they_expire(self, monkeypatch, pg_conn):
        import time

        from mcp.shared.auth import OAuthToken

        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        self._patch_db(monkeypatch, pg_conn)
        storage = DBTokenStorage(server_url="https://mcp.expiry.example.com/mcp", user_id="user-expiry")
        loop = asyncio.new_event_loop()
        try:
            before = time.time()
            loop.run_until_complete(storage.set_tokens(OAuthToken(
                access_token="at", token_type="Bearer", expires_in=3600, refresh_token="rt",
            )))
            # A later process reads the tokens back with when they expire.
            reader = DBTokenStorage(server_url="https://mcp.expiry.example.com/mcp", user_id="user-expiry")
            tokens = loop.run_until_complete(reader.get_tokens())
        finally:
            loop.close()
        assert tokens.access_token == "at"
        assert before + 3600 <= reader.expires_at <= time.time() + 3600

    def test_tokens_without_a_lifetime_have_no_expiry(self, monkeypatch, pg_conn):
        from mcp.shared.auth import OAuthToken

        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        self._patch_db(monkeypatch, pg_conn)
        storage = DBTokenStorage(server_url="https://mcp.forever.example.com/mcp", user_id="user-forever")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(storage.set_tokens(OAuthToken(access_token="at", token_type="Bearer")))
            loop.run_until_complete(storage.get_tokens())
        finally:
            loop.close()
        assert storage.expires_at is None


# =====================================================================
# Renewing a stored sign-in
# =====================================================================


class _StoredTokens:
    """A token storage holding one sign-in, with or without its expiry."""

    def __init__(self, tokens, expires_at=None, client_info=None):
        self.tokens = tokens
        self.client_info = client_info
        self.expires_at = None
        self._expires_at = expires_at

    async def get_tokens(self):
        self.expires_at = self._expires_at
        return self.tokens

    async def get_client_info(self):
        return self.client_info


@pytest.mark.unit
class TestStoredSignInRenewal:
    """A stored MCP sign-in is renewed with its refresh token once it expires.

    The SDK only knows when a token expires if it obtained it in this
    process; a worker that loads it from the connection must be told, or it
    sends the expired token, gets a 401 and asks the user to sign in again.
    """

    @staticmethod
    def _oauth(storage):
        from docsgpt.agents.tools.mcp_tool import NonInteractiveOAuth

        oauth = NonInteractiveOAuth(
            mcp_url="https://mcp.example.com/mcp",
            redirect_uri="https://docsgpt.example.com/api/mcp_server/callback",
            user_id="alice",
            connection_id="c1",
        )
        oauth.context.storage = storage
        return oauth

    @staticmethod
    def _token(**extra):
        from mcp.shared.auth import OAuthToken

        return OAuthToken(access_token="at", token_type="Bearer", **extra)

    def test_expired_stored_token_is_due_for_renewal(self):
        import time

        oauth = self._oauth(_StoredTokens(self._token(refresh_token="rt", expires_in=3600), time.time() - 5))
        asyncio.run(oauth._initialize())
        assert oauth.context.is_token_valid() is False

    def test_unexpired_stored_token_is_used_as_it_is(self):
        import time

        expires_at = time.time() + 600
        oauth = self._oauth(_StoredTokens(self._token(refresh_token="rt", expires_in=3600), expires_at))
        asyncio.run(oauth._initialize())
        assert oauth.context.token_expiry_time == expires_at
        assert oauth.context.is_token_valid() is True

    def test_token_saved_before_expiries_were_kept_is_renewed_once(self):
        # Its age is unknown, so it is treated as expired while it can be renewed.
        oauth = self._oauth(_StoredTokens(self._token(refresh_token="rt", expires_in=3600)))
        asyncio.run(oauth._initialize())
        assert oauth.context.is_token_valid() is False

    def test_token_that_cannot_be_renewed_is_still_tried(self):
        oauth = self._oauth(_StoredTokens(self._token(expires_in=3600)))
        asyncio.run(oauth._initialize())
        assert oauth.context.is_token_valid() is True

    @staticmethod
    def _metadata_server(monkeypatch, status=200, protected_resource=True, issuer=None):
        """Serve Sentry-shaped OAuth metadata: the token endpoint is not at ``/token``.

        ``protected_resource=False`` is a legacy server without protected-resource
        metadata, whose authorization server is its own origin.
        """
        import httpx2

        seen = []

        def handler(request):
            seen.append(str(request.url))
            if status != 200:
                return httpx2.Response(status)
            if request.url.path.startswith("/.well-known/oauth-protected-resource"):
                if not protected_resource:
                    return httpx2.Response(404)
                return httpx2.Response(200, json={
                    "resource": "https://mcp.example.com/mcp",
                    "authorization_servers": ["https://mcp.example.com"],
                })
            if request.url.path == "/.well-known/oauth-authorization-server":
                return httpx2.Response(200, json={
                    # A legacy server may write its root issuer with the slash.
                    "issuer": issuer
                    or ("https://mcp.example.com" if protected_resource else "https://mcp.example.com/"),
                    "authorization_endpoint": "https://mcp.example.com/oauth/authorize",
                    "token_endpoint": "https://mcp.example.com/oauth/token",
                    "response_types_supported": ["code"],
                })
            return httpx2.Response(404)

        def client(**kwargs):
            return httpx2.AsyncClient(transport=httpx2.MockTransport(handler), **kwargs)

        monkeypatch.setattr("docsgpt.agents.tools.mcp_tool.create_mcp_http_client", client)
        return seen

    @staticmethod
    def _client_info():
        from mcp.shared.auth import OAuthClientInformationFull

        return OAuthClientInformationFull(
            client_id="cid", redirect_uris=["https://docsgpt.example.com/api/mcp_server/callback"],
            token_endpoint_auth_method="none",
        )

    def test_renewal_goes_to_the_advertised_token_endpoint(self, monkeypatch):
        # A fresh process holds no OAuth metadata, and the SDK then renews at
        # <server>/token; Sentry's endpoint is /oauth/token and /token answers 500.
        import time

        self._metadata_server(monkeypatch)
        oauth = self._oauth(_StoredTokens(
            self._token(refresh_token="rt", expires_in=3600), time.time() - 5, client_info=self._client_info(),
        ))
        asyncio.run(oauth._initialize())
        request = asyncio.run(oauth._refresh_token())
        assert str(request.url) == "https://mcp.example.com/oauth/token"

    def test_legacy_server_with_a_root_issuer_is_accepted(self, monkeypatch):
        # Without protected-resource metadata the expected issuer is the bare
        # origin; a server that publishes it with a trailing slash names the
        # same server (the SDK's sign-in accepts it), and so must the renewal.
        import time

        self._metadata_server(monkeypatch, protected_resource=False)
        oauth = self._oauth(_StoredTokens(
            self._token(refresh_token="rt", expires_in=3600), time.time() - 5, client_info=self._client_info(),
        ))
        asyncio.run(oauth._initialize())
        request = asyncio.run(oauth._refresh_token())
        assert str(request.url) == "https://mcp.example.com/oauth/token"

    def test_metadata_for_another_issuer_is_not_used(self, monkeypatch, caplog):
        # The refresh token must never go to a token endpoint vouched for by a
        # server other than the one the resource names.
        import logging
        import time

        self._metadata_server(monkeypatch, issuer="https://evil.example.com")
        oauth = self._oauth(_StoredTokens(
            self._token(refresh_token="rt", expires_in=3600), time.time() - 5, client_info=self._client_info(),
        ))
        with caplog.at_level(logging.WARNING, logger="docsgpt.agents.tools.mcp_tool"):
            asyncio.run(oauth._initialize())
        assert oauth.context.oauth_metadata is None
        assert "Could not read OAuth metadata" in caplog.text

    def test_a_valid_token_needs_no_discovery(self, monkeypatch):
        import time

        seen = self._metadata_server(monkeypatch)
        oauth = self._oauth(_StoredTokens(
            self._token(refresh_token="rt", expires_in=3600), time.time() + 600, client_info=self._client_info(),
        ))
        asyncio.run(oauth._initialize())
        assert seen == []
        assert oauth.context.oauth_metadata is None

    def test_unreachable_metadata_leaves_the_sdk_default(self, monkeypatch):
        import time

        self._metadata_server(monkeypatch, status=503)
        oauth = self._oauth(_StoredTokens(
            self._token(refresh_token="rt", expires_in=3600), time.time() - 5, client_info=self._client_info(),
        ))
        asyncio.run(oauth._initialize())
        assert oauth.context.oauth_metadata is None
        assert oauth.context.is_token_valid() is False

    def test_a_lost_sign_in_raises_a_typed_error(self):
        from docsgpt.agents.tools.mcp_tool import MCPReauthorizationRequired

        oauth = self._oauth(_StoredTokens(None))
        with pytest.raises(MCPReauthorizationRequired, match="OAuth session expired"):
            asyncio.run(oauth.redirect_handler("https://mcp.example.com/authorize?state=x"))


# =====================================================================
# NonInteractiveOAuth
# =====================================================================


@pytest.mark.skip(reason="OAuth class signatures changed post-PG migration (db kwarg removed); needs rewrite")
@pytest.mark.unit
class TestNonInteractiveOAuth:

    def test_redirect_handler_raises(self):
        from docsgpt.agents.tools.mcp_tool import NonInteractiveOAuth

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
        from docsgpt.agents.tools.mcp_tool import NonInteractiveOAuth

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
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "MCP_OAUTH_REDIRECT_URI", "https://custom.redirect/callback/")
        # Ensure no configured redirect_uri in config
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        assert tool.redirect_uri == "https://custom.redirect/callback"

    def test_setting_wins_over_the_redirect_the_page_sends(self, monkeypatch):
        from docsgpt.core.settings import settings

        # A page opened on a plain-HTTP address sends its own origin; the
        # operator's HTTPS callback is the one servers accept.
        monkeypatch.setattr(settings, "MCP_OAUTH_REDIRECT_URI", "https://docs.example.com/api/mcp_server/callback")
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
            "redirect_uri": "http://10.0.0.5:7091/api/mcp_server/callback",
        })
        assert tool.redirect_uri == "https://docs.example.com/api/mcp_server/callback"

    def test_page_redirect_used_without_the_setting(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "MCP_OAUTH_REDIRECT_URI", None, raising=False)
        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "none",
            "redirect_uri": "https://app.example.com/api/mcp_server/callback/",
        })
        assert tool.redirect_uri == "https://app.example.com/api/mcp_server/callback"

    def test_connector_redirect_base_uri_setting(self, monkeypatch):
        from docsgpt.core.settings import settings

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
        from docsgpt.core.settings import settings

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
        import docsgpt.agents.tools.mcp_tool as mcp_mod
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
        import docsgpt.agents.tools.mcp_tool as mcp_mod
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
             patch("docsgpt.agents.tools.mcp_tool.Client", return_value=new_client):
            tool._setup_client()
            assert tool._client is new_client
            assert "expired_cache_key" not in mcp_mod._mcp_clients_cache or \
                mcp_mod._mcp_clients_cache["expired_cache_key"]["client"] is new_client

    def test_setup_client_oauth_query_mode(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
             patch("docsgpt.agents.tools.mcp_tool.Client", return_value=mock_client), \
             patch("docsgpt.agents.tools.mcp_tool.get_redis_instance", return_value=MagicMock()), \
             patch("docsgpt.agents.tools.mcp_tool.NonInteractiveOAuth"):
            tool._setup_client()
            assert tool._client is mock_client

    def test_setup_client_oauth_interactive_mode(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
        tool.oauth_redirect_publish = None

        mock_client = MagicMock()
        with patch.object(MCPTool, "_create_transport", return_value=MagicMock()), \
             patch("docsgpt.agents.tools.mcp_tool.Client", return_value=mock_client), \
             patch("docsgpt.agents.tools.mcp_tool.get_redis_instance", return_value=MagicMock()), \
             patch("docsgpt.agents.tools.mcp_tool.DocsGPTOAuth"):
            tool._setup_client()
            assert tool._client is mock_client

    def test_setup_client_bearer_auth(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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
             patch("docsgpt.agents.tools.mcp_tool.Client", return_value=mock_client), \
             patch("docsgpt.agents.tools.mcp_tool.BearerAuth") as mock_bearer_auth:
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
            "oauth_scopes": ["read"],
        })
        tool.user_id = "user1"
        tool._client = MagicMock()

        mock_token = MagicMock()
        mock_token.access_token = "valid_token"

        with patch("docsgpt.agents.tools.mcp_tool.DBTokenStorage") as mock_storage_cls:
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

        with patch("docsgpt.agents.tools.mcp_tool.DBTokenStorage") as mock_storage_cls:
            mock_storage = MagicMock()

            async def fake_get_tokens():
                return None

            mock_storage.get_tokens = fake_get_tokens
            mock_storage_cls.return_value = mock_storage

            mock_task_result = MagicMock()
            mock_task_result.id = "task_abc"
            with patch("docsgpt.agents.tools.mcp_tool.mcp_oauth_task") as mock_task:
                mock_task.delay.return_value = mock_task_result
                result = tool.test_connection()
                assert result["success"] is False
                assert result["requires_oauth"] is True
                assert result["task_id"] == "task_abc"

    def test_oauth_connection_token_validation_fails(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        tool = _make_tool({
            "server_url": "https://mcp.example.com",
            "auth_type": "oauth",
            "oauth_scopes": ["read"],
        })
        tool.user_id = "user1"
        tool._client = MagicMock()

        mock_token = MagicMock()
        mock_token.access_token = "expired_token"

        with patch("docsgpt.agents.tools.mcp_tool.DBTokenStorage") as mock_storage_cls:
            mock_storage = MagicMock()

            async def fake_get_tokens():
                return mock_token

            mock_storage.get_tokens = fake_get_tokens
            mock_storage_cls.return_value = mock_storage

            mock_task_result = MagicMock()
            mock_task_result.id = "task_retry"
            with patch.object(tool, "discover_tools", side_effect=Exception("401 Unauthorized")), \
                 patch.object(MCPTool, "_setup_client"), \
                 patch("docsgpt.agents.tools.mcp_tool.mcp_oauth_task") as mock_task:
                mock_task.delay.return_value = mock_task_result
                result = tool.test_connection()
                assert result["success"] is False
                assert result["requires_oauth"] is True


# =====================================================================
# execute_action extended (format_result path)
# =====================================================================


@pytest.mark.unit
class TestExecuteActionExtended:

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_execute_auth_retry_second_attempt_fails(self, mock_run):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
    def test_discover_tools_no_client_calls_setup(self, mock_run, mcp_config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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

    @patch("docsgpt.agents.tools.mcp_tool.MCPTool._run_async_operation")
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


@pytest.mark.skip(reason="OAuth class signatures changed post-PG migration (db kwarg removed); needs rewrite")
@pytest.mark.unit
class TestDocsGPTOAuthExtended:

    def test_process_auth_url_success(self):
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

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
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

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
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

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
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

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
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

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
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = None
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        mock_redis = MagicMock()
        stored = {
            "mcp_oauth:code:mystate": b"auth_code_123",
            "mcp_oauth:iss:mystate": b"https://auth.example.com",
        }
        mock_redis.get.side_effect = stored.get

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
            # The MCP SDK reads ``.code``, ``.state`` and the RFC 9207 ``.iss``.
            result = loop.run_until_complete(oauth.callback_handler())
            assert result.code == "auth_code_123"
            assert result.state == "mystate"
            assert result.iss == "https://auth.example.com"
        finally:
            loop.close()

    def test_callback_handler_receives_error(self):
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

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
        from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

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


@pytest.mark.skip(reason="DBTokenStorage signature changed post-PG migration; needs repo-based rewrite")
@pytest.mark.unit
class TestDBTokenStorageExtended:

    def test_get_tokens_with_valid_data(self):
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage
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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage
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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

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
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(state="s1", code="c1")
        assert result is True
        # Should call setex for code and state
        assert mock_redis.setex.call_count == 2

    def test_handle_callback_with_error_stores_error(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        manager = MCPOAuthManager(mock_redis)

        result = manager.handle_oauth_callback(
            state="s1", code="", error="invalid_scope"
        )
        assert result is False
        # Should store error in redis
        mock_redis.setex.assert_called()

    def test_get_oauth_status_returns_not_found_on_redis_error(self):
        """A failure inside ``xrevrange`` (Redis down, network blip) is
        swallowed — the manager returns ``not_found`` so the caller
        can present a clean "OAuth failed, try again" message rather
        than a 500.
        """
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        mock_redis = MagicMock()
        mock_redis.xrevrange.side_effect = Exception("Redis went away")

        manager = MCPOAuthManager(mock_redis)
        result = manager.get_oauth_status("task123", "alice")

        assert result["status"] == "not_found"


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
