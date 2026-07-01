"""Flask-free service exposing a principal's artifacts as MCP Resources.

The MCP server (``application/mcp_server.py``) authenticates a request with
``Authorization: Bearer <agent-api-key>``; that key resolves to the owning
``user_id`` via ``AgentsRepository.find_by_key`` (the same api_key->owner path
as the HTTP artifact routes). Resources are scoped strictly to that principal:
``resources/list`` returns only the principal's owned artifacts, and
``resources/read`` re-checks ownership before serving any bytes. An
unresolvable principal yields an empty list / a denied read -- never another
principal's artifact.

``resources/list`` returns FastMCP ``Resource`` objects so they pass straight
through the server's list/dedupe/wire pipeline; ``resources/read`` is served by
the MCP middleware, which streams the real bytes for each ``artifact://`` uri.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from fastmcp.resources.base import Resource
from fastmcp.resources.types import TextResource
from sqlalchemy.exc import DataError, DBAPIError

from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.session import db_readonly
from application.storage.storage_creator import StorageCreator

logger = logging.getLogger(__name__)

# artifact://{artifact_id}/v{version}
_URI_RE = re.compile(r"^artifact://(?P<id>[^/]+)/v(?P<version>\d+)$")

# Max resources advertised by ``resources/list`` so the model is not flooded
# with thousands of rows even when a principal owns far more artifacts.
_RESOURCE_LIST_LIMIT = 500

# mime types served as inline ``text`` rather than base64 ``blob``.
_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_EXACT = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-ndjson",
    "image/svg+xml",
}
_TEXT_MIME_SUFFIXES = ("+json", "+xml")


class ResourceDenied(Exception):
    """The principal may not access the requested resource (unauth or foreign)."""


class ResourceNotFound(Exception):
    """The requested ``artifact://`` uri does not resolve to a stored version."""


@dataclass(frozen=True)
class ArtifactReadResult:
    """Materialized artifact contents for a ``resources/read`` response."""

    uri: str
    mime_type: str
    text: Optional[str] = None
    blob_b64: Optional[str] = None


def _read_cap() -> int:
    """Return the per-read byte cap, or 0 (no cap) when the setting disables it."""
    return int(getattr(settings, "ARTIFACT_RESOURCE_READ_MAX_BYTES", 0) or 0)


def _cap_text(text: str) -> str:
    """Truncate ``text`` to the read cap; unchanged when the cap is disabled."""
    cap = _read_cap()
    return text[:cap] if cap > 0 else text


def _is_texty(mime_type: str) -> bool:
    """Return True when ``mime_type`` should be served as inline UTF-8 text."""
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if mime in _TEXT_MIME_EXACT:
        return True
    if any(mime.startswith(p) for p in _TEXT_MIME_PREFIXES):
        return True
    return any(mime.endswith(s) for s in _TEXT_MIME_SUFFIXES)


def _resolve_agent(api_key: Optional[str]) -> Optional[dict]:
    """Resolve a Bearer api_key to its owning agent row (carries ``id`` + ``user_id``).

    Returns the whole agent so callers can scope artifact visibility to that agent's
    conversations, not the owner's entire corpus. None when unresolvable.
    """
    if not api_key:
        return None
    try:
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)
    except Exception:
        logger.exception("artifact resource: principal resolution failed")
        return None
    if not agent or not agent.get("user_id") or not agent.get("id"):
        return None
    return agent


def _resource_uri(artifact_id: str, version: int) -> str:
    """Build the stable ``artifact://{id}/v{version}`` resource uri."""
    return f"artifact://{artifact_id}/v{version}"


def list_artifact_resources(api_key: Optional[str]) -> List[Resource]:
    """List the calling principal's artifacts as FastMCP resources (empty if unresolved).

    Returns FastMCP ``Resource`` objects (not raw ``mcp.types.Resource``): the
    server's ``resources/list`` pipeline reads FastMCP-only attributes
    (``.version``, ``.auth``, ``is_enabled``) and calls ``to_mcp_resource()`` for
    the wire encoding, so a raw ``mcp.types.Resource`` mixed into the list would
    raise ``AttributeError``. The placeholder ``text`` is never served -- the
    middleware's ``on_read_resource`` intercepts every ``artifact://`` read and
    streams the real bytes via :func:`read_artifact_resource`.
    """
    agent = _resolve_agent(api_key)
    if not agent:
        return []
    try:
        with db_readonly() as conn:
            rows = ArtifactsRepository(conn).list_artifacts_for_agent(
                str(agent["id"]), str(agent["user_id"])
            )
    except Exception:
        logger.exception("artifact resource: list failed")
        return []

    resources: List[Resource] = []
    for row in rows[:_RESOURCE_LIST_LIMIT]:
        artifact_id = str(row.get("id"))
        version = row.get("current_version") or 1
        title = row.get("title") or f"artifact-{artifact_id}"
        resources.append(
            TextResource(
                uri=_resource_uri(artifact_id, version),
                name=title,
                title=title,
                description=f"DocsGPT {row.get('kind') or 'file'} artifact",
                mime_type=_kind_mime_hint(row.get("kind")),
                text="",
            )
        )
    return resources


def _kind_mime_hint(kind: Optional[str]) -> str:
    """Concrete mime hint for a list row; ambiguous kinds fall back to octet-stream."""
    # Only kinds with a single unambiguous mime get a concrete type; everything
    # else stays octet-stream so a list row never mismatches the read's bytes.
    return {
        "html": "text/html",
        "data": "application/json",
    }.get((kind or "").lower(), "application/octet-stream")


def read_artifact_resource(api_key: Optional[str], uri: str) -> ArtifactReadResult:
    """Authorize and materialize an ``artifact://`` resource for the principal.

    Raises:
        ResourceDenied: principal unresolved, or the artifact is not theirs.
        ResourceNotFound: uri malformed, or the version/file does not exist.
    """
    match = _URI_RE.match(uri or "")
    if not match:
        raise ResourceNotFound(f"unsupported resource uri: {uri!r}")
    artifact_id = match.group("id")
    version = int(match.group("version"))

    # A non-UUID id would reach a ``CAST(:id AS uuid)`` and raise a DB DataError;
    # gate it up front like the HTTP artifact routes do.
    if not looks_like_uuid(artifact_id):
        raise ResourceNotFound(f"artifact {artifact_id} not found")

    agent = _resolve_agent(api_key)
    if not agent:
        raise ResourceDenied("unauthenticated")
    user_id = str(agent["user_id"])
    agent_id = str(agent["id"])

    try:
        with db_readonly() as conn:
            repo = ArtifactsRepository(conn)
            artifact = repo.get_artifact(artifact_id)
            if artifact is None:
                raise ResourceNotFound(f"artifact {artifact_id} not found")
            # Ownership is the first authz point: never serve another principal's
            # artifact over MCP, regardless of conversation/workflow parent sharing.
            if str(artifact.get("user_id")) != user_id:
                raise ResourceDenied("forbidden")
            # Agent scope is the second: a per-agent key only reads artifacts from
            # its own conversations, not the owner's other agents / workflow runs.
            if not repo.artifact_in_agent_scope(artifact_id, agent_id):
                raise ResourceDenied("forbidden")
            version_row = repo.get_version(artifact_id, version)
    except (DataError, DBAPIError) as exc:
        raise ResourceNotFound(f"artifact {artifact_id} not found") from exc

    if version_row is None:
        raise ResourceNotFound(f"version {version} of {artifact_id} not found")

    mime_type = version_row.get("mime_type") or "application/octet-stream"
    uri = _resource_uri(artifact_id, version)

    # Prefer the stored preview/extracted text for texty kinds: it is already
    # bounded and avoids a storage round-trip.
    preview = version_row.get("preview_text")
    if _is_texty(mime_type) and preview:
        return ArtifactReadResult(uri=uri, mime_type=mime_type, text=_cap_text(preview))

    storage_path = version_row.get("storage_path")
    if not storage_path:
        if _is_texty(mime_type) and preview is not None:
            return ArtifactReadResult(uri=uri, mime_type=mime_type, text=_cap_text(preview))
        raise ResourceNotFound(f"version {version} of {artifact_id} has no stored bytes")

    try:
        data = _read_capped_bytes(storage_path)
    except FileNotFoundError as exc:
        raise ResourceNotFound(f"version {version} of {artifact_id} has no stored bytes") from exc

    if _is_texty(mime_type):
        # ``errors="ignore"`` keeps valid text texty even when the cap splits a
        # multibyte char at the boundary, instead of demoting it to a blob.
        return ArtifactReadResult(uri=uri, mime_type=mime_type, text=data.decode("utf-8", errors="ignore"))
    return ArtifactReadResult(
        uri=uri, mime_type=mime_type, blob_b64=base64.b64encode(data).decode("ascii")
    )


def _read_capped_bytes(storage_path: str) -> bytes:
    """Read at most ``_read_cap()`` bytes of a stored artifact version (0 == all)."""
    cap = _read_cap()
    storage = StorageCreator.get_storage()
    file_obj = storage.get_file(storage_path)
    try:
        return file_obj.read(cap) if cap > 0 else file_obj.read()
    finally:
        close = getattr(file_obj, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.debug("artifact resource: file close failed", exc_info=True)
