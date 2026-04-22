"""FastMCP server exposing DocsGPT retrieval over streamable HTTP.

Mounted at ``/mcp`` by ``application/asgi.py``. Bearer tokens are the
existing DocsGPT agent API keys — no new credential surface.

The tool reads the ``Authorization`` header directly via
``get_http_headers(include={"authorization"})``. The ``include`` kwarg
is required: by default ``get_http_headers`` strips ``authorization``
(and a handful of other hop-by-hop headers) so they aren't forwarded
to downstream services — since we deliberately want the caller's
token, we opt it back in.
"""

from __future__ import annotations

import asyncio
import logging

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from application.services.search_service import (
    InvalidAPIKey,
    SearchFailed,
    search,
)

logger = logging.getLogger(__name__)

mcp = FastMCP("docsgpt")


def _extract_bearer_token() -> str | None:
    auth = get_http_headers(include={"authorization"}).get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth.split(None, 1)[1]


@mcp.tool
async def search_docs(query: str, chunks: int = 5) -> list[dict]:
    """Search the caller's DocsGPT knowledge base.

    Authentication is via ``Authorization: Bearer <agent-api-key>`` on
    the MCP request — the same opaque key that ``/api/search`` accepts
    in its JSON body. Returns at most ``chunks`` hits, each a dict with
    ``text``, ``title``, ``source`` keys.
    """
    api_key = _extract_bearer_token()
    if not api_key:
        raise PermissionError("Missing Bearer token")
    try:
        return await asyncio.to_thread(search, api_key, query, chunks)
    except InvalidAPIKey as exc:
        raise PermissionError("Invalid API key") from exc
    except SearchFailed:
        logger.exception("search_docs failed")
        raise
