"""Tests for docsgpt/agents/mcp_apps.py, the MCP Apps (``io.modelcontextprotocol/ui``) contract."""

import base64
import json

import pytest

from docsgpt.agents import mcp_apps


@pytest.fixture
def apps_on(monkeypatch):
    """MCP Apps on, with the dev defaults: the API on localhost, the Vite app on :5173."""
    monkeypatch.setattr(mcp_apps.settings, "MCP_APPS_ENABLED", True)
    monkeypatch.setattr(mcp_apps.settings, "MCP_APPS_SANDBOX_URL", None)
    monkeypatch.setattr(mcp_apps.settings, "API_URL", "http://localhost:7091")
    monkeypatch.setattr(mcp_apps.settings, "OIDC_FRONTEND_URL", None)
    monkeypatch.setattr(mcp_apps.settings, "AGENT_TRUSTED_ORIGINS", [])


@pytest.mark.unit
class TestToolUiMetadata:
    def test_keeps_resource_uri_and_visibility(self):
        meta = {"ui": {"resourceUri": "ui://excalidraw/mcp-app.html", "visibility": ["model", "app"], "x": 1}}
        assert mcp_apps.tool_ui_metadata(meta) == {
            "resourceUri": "ui://excalidraw/mcp-app.html",
            "visibility": ["model", "app"],
        }

    def test_reads_the_deprecated_flat_resource_uri(self):
        assert mcp_apps.tool_ui_metadata({"ui/resourceUri": "ui://a/b.html"}) == {"resourceUri": "ui://a/b.html"}

    def test_drops_a_resource_that_is_not_ui_scheme(self):
        assert mcp_apps.tool_ui_metadata({"ui": {"resourceUri": "https://evil.example/app.html"}}) == {}

    def test_malformed_visibility_fails_closed(self):
        assert mcp_apps.tool_ui_metadata({"ui": {"visibility": "app"}}) == {"visibility": []}
        assert mcp_apps.tool_ui_metadata({"ui": {"visibility": ["app", 3]}}) == {"visibility": []}

    def test_no_metadata(self):
        assert mcp_apps.tool_ui_metadata(None) == {}
        assert mcp_apps.tool_ui_metadata({"other": True}) == {}


@pytest.mark.unit
class TestVisibility:
    def test_default_is_model_and_app(self):
        assert mcp_apps.visible_to_model({"name": "a"})
        assert mcp_apps.visible_to_app({"name": "a"})

    def test_app_only(self):
        action = {"name": "save_checkpoint", "ui": {"visibility": ["app"]}}
        assert not mcp_apps.visible_to_model(action)
        assert mcp_apps.visible_to_app(action)

    def test_model_only(self):
        action = {"name": "read_me", "ui": {"visibility": ["model"]}}
        assert mcp_apps.visible_to_model(action)
        assert not mcp_apps.visible_to_app(action)

    def test_empty_visibility_is_neither(self):
        action = {"name": "x", "ui": {"visibility": []}}
        assert not mcp_apps.visible_to_model(action)
        assert not mcp_apps.visible_to_app(action)


@pytest.mark.unit
class TestAppMimeType:
    @pytest.mark.parametrize(
        "mime",
        ["text/html;profile=mcp-app", 'text/html; profile="mcp-app"', "TEXT/HTML;profile = mcp-app"],
    )
    def test_accepts_spellings(self, mime):
        assert mcp_apps.is_app_mime_type(mime)

    @pytest.mark.parametrize("mime", ["text/html", "text/plain;profile=mcp-app", "", None, "text/html;profile=x"])
    def test_rejects_others(self, mime):
        assert not mcp_apps.is_app_mime_type(mime)


@pytest.mark.unit
class TestBuildCsp:
    def test_restrictive_default(self):
        csp = mcp_apps.build_csp(None, ["http://localhost:5173"])
        assert "connect-src 'none'" in csp
        assert "frame-src 'none'" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors http://localhost:5173" in csp
        assert "'self'" not in csp.split("base-uri")[0]

    def test_declared_domains(self):
        csp = mcp_apps.build_csp(
            {"resourceDomains": ["https://esm.sh"], "connectDomains": ["https://esm.sh"]}, ["http://localhost:5173"]
        )
        assert "script-src 'unsafe-inline' 'unsafe-eval' blob: data: https://esm.sh" in csp
        assert "connect-src https://esm.sh" in csp

    @pytest.mark.parametrize(
        "domain",
        ["https://a.com; script-src *", "'unsafe-eval'", "https://a.com https://b.com", "*", "javascript:alert(1)"],
    )
    def test_undeclarable_domains_are_dropped(self, domain):
        csp = mcp_apps.build_csp({"connectDomains": [domain]}, [])
        assert "connect-src 'none'" in csp

    def test_frame_ancestors_none_without_hosts(self):
        assert "frame-ancestors 'none'" in mcp_apps.build_csp(None, [])


@pytest.mark.unit
class TestAllowAttribute:
    def test_maps_known_permissions(self):
        assert mcp_apps.allow_attribute({"clipboardWrite": {}, "camera": {}}) == "camera; clipboard-write"

    def test_ignores_unknown(self):
        assert mcp_apps.allow_attribute({"usb": {}}) == ""
        assert mcp_apps.allow_attribute(None) == ""


@pytest.mark.unit
class TestSandbox:
    def test_dev_default_swaps_the_loopback_host(self, apps_on):
        assert mcp_apps.sandbox_url() == "http://127.0.0.1:7091/api/mcp_apps/sandbox"
        assert mcp_apps.enabled()

    def test_configured_url(self, apps_on, monkeypatch):
        monkeypatch.setattr(mcp_apps.settings, "API_URL", "https://docs.example.com")
        monkeypatch.setattr(mcp_apps.settings, "MCP_APPS_SANDBOX_URL", "https://sandbox.example.com/api/mcp_apps/sandbox")
        assert mcp_apps.sandbox_url() == "https://sandbox.example.com/api/mcp_apps/sandbox"

    def test_public_api_without_a_sandbox_url_is_off(self, apps_on, monkeypatch):
        monkeypatch.setattr(mcp_apps.settings, "API_URL", "https://docs.example.com")
        assert mcp_apps.sandbox_url() is None
        assert not mcp_apps.enabled()

    def test_sandbox_on_the_app_origin_is_refused(self, apps_on, monkeypatch):
        monkeypatch.setattr(mcp_apps.settings, "API_URL", "https://docs.example.com")
        monkeypatch.setattr(mcp_apps.settings, "MCP_APPS_SANDBOX_URL", "https://docs.example.com/api/mcp_apps/sandbox")
        assert mcp_apps.sandbox_url() is None

    def test_off_switch(self, apps_on, monkeypatch):
        monkeypatch.setattr(mcp_apps.settings, "MCP_APPS_ENABLED", False)
        assert not mcp_apps.enabled()

    def test_host_origins_exclude_the_sandbox(self, apps_on):
        origins = mcp_apps.host_origins()
        assert "http://localhost:5173" in origins
        assert "http://127.0.0.1:7091" not in origins

    def test_sandbox_page_lists_only_host_origins(self, apps_on):
        page = mcp_apps.sandbox_page(["http://localhost:5173"])
        assert json.dumps(["http://localhost:5173"]) in page
        assert "sandbox-proxy-ready" in page

    def test_sandbox_page_escapes_script_breakout(self):
        page = mcp_apps.sandbox_page(["http://a</script><script>alert(1)//"])
        assert "</script><script>alert(1)" not in page


@pytest.mark.unit
class TestAppResult:
    def test_keeps_content_and_structured_content(self):
        from mcp.types import TextContent

        class Result:
            content = [TextContent(type="text", text="Diagram displayed!")]
            structured_content = {"checkpointId": "abc"}
            is_error = False

        assert mcp_apps.app_result(Result()) == {
            "content": [{"type": "text", "text": "Diagram displayed!"}],
            "structuredContent": {"checkpointId": "abc"},
            "isError": False,
        }

    def test_over_the_bound_keeps_structured_content(self):
        from mcp.types import TextContent

        class Result:
            content = [TextContent(type="text", text="x" * (mcp_apps.APP_RESULT_MAX_CHARS + 1))]
            structured_content = {"k": "v"}
            is_error = False

        bounded = mcp_apps.app_result(Result())
        assert bounded["content"] == []
        assert bounded["structuredContent"] == {"k": "v"}

    def test_plain_dict_result(self):
        assert mcp_apps.app_result({"content": [{"type": "text", "text": "a"}], "isError": True}) == {
            "content": [{"type": "text", "text": "a"}],
            "isError": True,
        }


@pytest.mark.unit
class TestResourceHtml:
    def test_text_resource(self):
        class Contents:
            mime_type = "text/html;profile=mcp-app"
            text = "<html></html>"
            meta = {"ui": {"csp": {"connectDomains": ["https://esm.sh"]}, "prefersBorder": True}}

        view = mcp_apps.resource_view([Contents()], listing_meta=None)
        assert view["html"] == "<html></html>"
        assert view["csp"] == {"connectDomains": ["https://esm.sh"]}
        assert view["prefersBorder"] is True

    def test_blob_resource_and_listing_meta_fallback(self):
        class Contents:
            mime_type = "text/html;profile=mcp-app"
            blob = base64.b64encode(b"<html>b</html>").decode()
            meta = None

        view = mcp_apps.resource_view([Contents()], listing_meta={"ui": {"permissions": {"clipboardWrite": {}}}})
        assert view["html"] == "<html>b</html>"
        assert view["permissions"] == {"clipboardWrite": {}}

    def test_wrong_mime_type(self):
        class Contents:
            mime_type = "text/html"
            text = "<html></html>"
            meta = None

        with pytest.raises(ValueError):
            mcp_apps.resource_view([Contents()], listing_meta=None)
