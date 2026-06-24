"""FastMCP server exposing DocsGPT retrieval + artifacts over streamable HTTP.

Mounted at ``/mcp`` by ``application/asgi.py``. Bearer tokens are the
existing DocsGPT agent API keys — no new credential surface. The
``search_docs`` tool searches the caller's knowledge base; the artifact
resources middleware exposes the caller's own artifacts as MCP resources
(``resources/list`` / ``resources/read`` over ``artifact://`` URIs),
scoped strictly to the Bearer key's owning principal.

The tool reads the ``Authorization`` header directly via
``get_http_headers(include={"authorization"})``. The ``include`` kwarg
is required: by default ``get_http_headers`` strips ``authorization``
(and a handful of other hop-by-hop headers) so they aren't forwarded
to downstream services — since we deliberately want the caller's
token, we opt it back in.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Sequence

from fastmcp import FastMCP
from fastmcp.resources import ResourceContent, ResourceResult
from fastmcp.resources.base import Resource
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from application.services.artifact_resource_service import (
    ArtifactReadResult,
    ResourceDenied,
    ResourceNotFound,
    list_artifact_resources,
    read_artifact_resource,
)
from application.services.search_service import (
    InvalidAPIKey,
    SearchFailed,
    search,
)

logger = logging.getLogger(__name__)


def _extract_bearer_token() -> str | None:
    auth = get_http_headers(include={"authorization"}).get("authorization", "")
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


def _read_result_to_mcp(result: ArtifactReadResult) -> ResourceResult:
    """Wrap a service read result as a FastMCP ``ResourceResult`` (text or blob)."""
    if result.blob_b64 is not None:
        raw = base64.b64decode(result.blob_b64)
        return ResourceResult([ResourceContent(raw, mime_type=result.mime_type)])
    return ResourceResult([ResourceContent(result.text or "", mime_type=result.mime_type)])


class ArtifactResourcesMiddleware(Middleware):
    """Expose the calling principal's artifacts as MCP resources (read/list).

    The principal is the Bearer api_key's owner; resources are scoped to that
    owner and a foreign/unauthenticated read is denied. Static resources
    registered on the server (if any) are preserved by chaining ``call_next``.
    """

    async def on_list_resources(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Sequence[Resource]:
        """Append the principal's artifact resources to the static resource list."""
        existing = list(await call_next(context))
        try:
            artifacts = await asyncio.to_thread(
                list_artifact_resources, _extract_bearer_token()
            )
        except Exception:
            logger.exception("on_list_resources: artifact listing failed")
            return existing
        existing.extend(artifacts)
        return existing

    async def on_read_resource(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> ResourceResult:
        """Serve ``artifact://`` reads from the artifact store; defer others."""
        uri = str(getattr(context.message, "uri", ""))
        if not uri.startswith("artifact://"):
            return await call_next(context)
        try:
            result = await asyncio.to_thread(
                read_artifact_resource, _extract_bearer_token(), uri
            )
        except ResourceDenied as exc:
            raise PermissionError(str(exc) or "forbidden") from exc
        except ResourceNotFound as exc:
            raise ValueError(str(exc) or "resource not found") from exc
        return _read_result_to_mcp(result)


mcp = FastMCP("docsgpt")
mcp.add_middleware(ArtifactResourcesMiddleware())


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
