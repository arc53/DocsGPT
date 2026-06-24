"""Tests for application/mcp_server.py.

The server module exposes one FastMCP tool, ``search_docs``, that reads
the caller's ``Authorization: Bearer <key>`` header via
``get_http_headers()`` and delegates to
``application.services.search_service.search``. These tests exercise
the tool directly by patching ``get_http_headers`` and ``search``; the
full HTTP-layer plumbing (mount, lifespan, session handshake) is
covered by ``tests/test_asgi.py``.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestSearchDocsTool:
    @pytest.mark.asyncio
    async def test_missing_bearer_raises_permission_error(self):
        from application.mcp_server import search_docs

        with patch(
            "application.mcp_server.get_http_headers", return_value={}
        ):
            with pytest.raises(PermissionError):
                await search_docs(query="hi")

    @pytest.mark.asyncio
    async def test_non_bearer_header_raises_permission_error(self):
        from application.mcp_server import search_docs

        with patch(
            "application.mcp_server.get_http_headers",
            return_value={"authorization": "Basic dXNlcjpwYXNz"},
        ):
            with pytest.raises(PermissionError):
                await search_docs(query="hi")

    @pytest.mark.asyncio
    async def test_blank_bearer_token_raises_permission_error(self):
        from application.mcp_server import search_docs

        with patch(
            "application.mcp_server.get_http_headers",
            return_value={"authorization": "Bearer    "},
        ):
            with pytest.raises(PermissionError):
                await search_docs(query="hi")

    @pytest.mark.asyncio
    async def test_invalid_api_key_raises_permission_error(self):
        from application.mcp_server import search_docs
        from application.services.search_service import InvalidAPIKey

        with (
            patch(
                "application.mcp_server.get_http_headers",
                return_value={"authorization": "Bearer bogus"},
            ),
            patch(
                "application.mcp_server.search", side_effect=InvalidAPIKey()
            ),
        ):
            with pytest.raises(PermissionError):
                await search_docs(query="hi")

    @pytest.mark.asyncio
    async def test_search_failed_bubbles_up(self):
        from application.mcp_server import search_docs
        from application.services.search_service import SearchFailed

        with (
            patch(
                "application.mcp_server.get_http_headers",
                return_value={"authorization": "Bearer k"},
            ),
            patch(
                "application.mcp_server.search",
                side_effect=SearchFailed("boom"),
            ),
        ):
            with pytest.raises(SearchFailed):
                await search_docs(query="hi")

    @pytest.mark.asyncio
    async def test_happy_path_passes_args_and_returns_hits(self):
        from application.mcp_server import search_docs

        hits = [{"text": "t", "title": "T", "source": "s"}]
        with (
            patch(
                "application.mcp_server.get_http_headers",
                return_value={"authorization": "Bearer the-key"},
            ),
            patch(
                "application.mcp_server.search", return_value=hits
            ) as mock_search,
        ):
            out = await search_docs(query="q", chunks=7)
        assert out == hits
        mock_search.assert_called_once_with("the-key", "q", 7)

    @pytest.mark.asyncio
    async def test_default_chunks_is_5(self):
        from application.mcp_server import search_docs

        with (
            patch(
                "application.mcp_server.get_http_headers",
                return_value={"authorization": "Bearer k"},
            ),
            patch(
                "application.mcp_server.search", return_value=[]
            ) as mock_search,
        ):
            await search_docs(query="q")
        mock_search.assert_called_once_with("k", "q", 5)

    @pytest.mark.asyncio
    async def test_bearer_scheme_case_insensitive(self):
        from application.mcp_server import search_docs

        with (
            patch(
                "application.mcp_server.get_http_headers",
                return_value={"authorization": "bearer lowercase-scheme"},
            ),
            patch(
                "application.mcp_server.search", return_value=[]
            ) as mock_search,
        ):
            await search_docs(query="q")
        mock_search.assert_called_once_with("lowercase-scheme", "q", 5)


async def _call_next_empty(context):
    """Stand-in downstream handler returning no static resources."""
    return []


@pytest.mark.unit
class TestArtifactResourcesMiddleware:
    @pytest.mark.asyncio
    async def test_list_appends_principal_artifacts(self):
        import mcp.types as mt
        from application.mcp_server import ArtifactResourcesMiddleware

        mw = ArtifactResourcesMiddleware()
        res = mt.Resource(uri="artifact://a/v1", name="x", mimeType="text/plain")
        with (
            patch("application.mcp_server._extract_bearer_token", return_value="k"),
            patch(
                "application.mcp_server.list_artifact_resources", return_value=[res]
            ),
        ):
            out = await mw.on_list_resources(SimpleNamespace(), _call_next_empty)
        assert [str(r.uri) for r in out] == ["artifact://a/v1"]

    @pytest.mark.asyncio
    async def test_read_text_wraps_as_text_contents(self):
        from application.mcp_server import ArtifactResourcesMiddleware
        from application.services.artifact_resource_service import ArtifactReadResult

        mw = ArtifactResourcesMiddleware()
        ctx = SimpleNamespace(message=SimpleNamespace(uri="artifact://a/v2"))
        rr = ArtifactReadResult(uri="artifact://a/v2", mime_type="text/csv", text="a,b")
        with (
            patch("application.mcp_server._extract_bearer_token", return_value="k"),
            patch(
                "application.mcp_server.read_artifact_resource", return_value=rr
            ),
        ):
            result = await mw.on_read_resource(ctx, _call_next_empty)
        out = result.to_mcp_result("artifact://a/v2").contents[0]
        assert out.text == "a,b"
        assert out.mimeType == "text/csv"

    @pytest.mark.asyncio
    async def test_read_blob_wraps_as_blob_contents(self):
        import base64

        from application.mcp_server import ArtifactResourcesMiddleware
        from application.services.artifact_resource_service import ArtifactReadResult

        mw = ArtifactResourcesMiddleware()
        ctx = SimpleNamespace(message=SimpleNamespace(uri="artifact://a/v1"))
        blob = base64.b64encode(b"\x89PNG").decode("ascii")
        rr = ArtifactReadResult(uri="artifact://a/v1", mime_type="image/png", blob_b64=blob)
        with (
            patch("application.mcp_server._extract_bearer_token", return_value="k"),
            patch(
                "application.mcp_server.read_artifact_resource", return_value=rr
            ),
        ):
            result = await mw.on_read_resource(ctx, _call_next_empty)
        out = result.to_mcp_result("artifact://a/v1").contents[0]
        assert out.mimeType == "image/png"
        assert base64.b64decode(out.blob) == b"\x89PNG"

    @pytest.mark.asyncio
    async def test_non_artifact_uri_is_deferred(self):
        from application.mcp_server import ArtifactResourcesMiddleware

        mw = ArtifactResourcesMiddleware()
        ctx = SimpleNamespace(message=SimpleNamespace(uri="https://example.com/x"))
        sentinel = object()

        async def _call_next(context):
            return sentinel

        with patch(
            "application.mcp_server.read_artifact_resource"
        ) as mock_read:
            out = await mw.on_read_resource(ctx, _call_next)
        assert out is sentinel
        mock_read.assert_not_called()

    @pytest.mark.asyncio
    async def test_denied_read_raises_permission_error(self):
        from application.mcp_server import ArtifactResourcesMiddleware
        from application.services.artifact_resource_service import ResourceDenied

        mw = ArtifactResourcesMiddleware()
        ctx = SimpleNamespace(message=SimpleNamespace(uri="artifact://foreign/v1"))
        with (
            patch("application.mcp_server._extract_bearer_token", return_value="k"),
            patch(
                "application.mcp_server.read_artifact_resource",
                side_effect=ResourceDenied("forbidden"),
            ),
        ):
            with pytest.raises(PermissionError):
                await mw.on_read_resource(ctx, _call_next_empty)
