"""Tests for application/mcp_server.py.

The server module exposes one FastMCP tool, ``search_docs``, that reads
the caller's ``Authorization: Bearer <key>`` header via
``get_http_headers()`` and delegates to
``application.services.search_service.search``. These tests exercise
the tool directly by patching ``get_http_headers`` and ``search``; the
full HTTP-layer plumbing (mount, lifespan, session handshake) is
covered by ``tests/test_asgi.py``.
"""

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
