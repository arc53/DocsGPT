"""``GET /api/artifacts/{artifact_id}/download`` — an artifact version's bytes.

A native-async Starlette route mounted ahead of Flask in ``docsgpt/asgi.py``,
so a large download to a slow client streams from the event loop instead of
pinning a WSGI threadpool slot for the whole transfer. Authorization is the
same parent-derived check the Flask artifact routes use; the database reads
and storage calls run in worker threads.
"""

from __future__ import annotations

import io
import logging
import os
import re
import unicodedata
from functools import partial
from typing import AsyncIterator, BinaryIO, Mapping, Optional, Tuple
from urllib.parse import quote

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from docsgpt.api.asgi_auth import authenticate, bind_log_context, json_error
from docsgpt.api.asgi_stream import ClosingStreamingResponse
from docsgpt.api.user.artifacts.authz import authorize_artifact, principal_for
from docsgpt.core.settings import settings
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.storage.storage_creator import StorageCreator

logger = logging.getLogger(__name__)

# Presigned-URL TTL for private S3 artifact downloads (seconds).
_PRESIGNED_URL_TTL = 300

_ARTIFACT_URL_ENVELOPE_MIME = "application/vnd.docsgpt.artifact-url+json"

_CHUNK_SIZE = 65536


def _sanitize_header_filename(filename: Optional[str], fallback: str) -> str:
    """Strip CRLF / quotes from a display filename for a Content-Disposition header."""
    if not filename:
        return fallback
    cleaned = re.sub(r'[\r\n"]', "", str(filename)).strip()
    return cleaned or fallback


def _ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _content_disposition(filename: Optional[str], artifact_id: str) -> str:
    """Build an ``attachment`` Content-Disposition value that any filename can travel in.

    Header values are Latin-1, so a non-ASCII name gets an ASCII ``filename``
    fallback plus an RFC 5987 ``filename*`` carrying the real name.
    """
    name = _sanitize_header_filename(filename, f"artifact-{artifact_id}")
    if name.isascii():
        return f'attachment; filename="{name}"'
    stem, ext = os.path.splitext(name)
    ascii_stem = _ascii_fold(stem).strip()
    fallback = f"{ascii_stem or f'artifact-{artifact_id}'}{_ascii_fold(ext)}"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def _load_version(
    artifact_id: str, decoded_token: Optional[dict], query: Mapping[str, str]
) -> Tuple[Optional[dict], Optional[Tuple[str, int]]]:
    """Authorize the caller and fetch the requested version row; runs in a worker thread.

    Returns:
        tuple: ``(version_row, None)`` or ``(None, (message, status))``.
    """
    principal = principal_for(decoded_token, query.get("api_key"))
    with db_readonly() as conn:
        repo = ArtifactsRepository(conn)
        artifact = repo.get_artifact(artifact_id)
        if artifact is None:
            return None, ("Artifact not found", 404)
        if not authorize_artifact(conn, artifact, principal, args=query):
            return None, ("Forbidden", 403)
        version = artifact.get("current_version")
        version_arg = query.get("version")
        if version_arg is not None:
            try:
                version = int(version_arg)
            except ValueError:
                return None, ("Invalid version", 400)
        version_row = repo.get_version(artifact_id, version)
    if version_row is None:
        return None, ("Version not found", 404)
    return version_row, None


async def _read_chunks(file_obj: BinaryIO) -> AsyncIterator[bytes]:
    """Yield the file in chunks; reads from disk or a socket hop to a worker thread."""
    in_memory = isinstance(file_obj, io.BytesIO)
    while True:
        if in_memory:
            chunk = file_obj.read(_CHUNK_SIZE)
        else:
            chunk = await anyio.to_thread.run_sync(file_obj.read, _CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


async def _close_file(file_obj: BinaryIO) -> None:
    """Close the handle; closing anything but an in-memory buffer runs in a worker thread."""
    close = getattr(file_obj, "close", None)
    if not callable(close):
        return
    if isinstance(file_obj, io.BytesIO):
        close()
    else:
        await anyio.to_thread.run_sync(close)


async def download_artifact(request: Request) -> Response:
    """Serve an artifact version: a 302 (or a JSON URL envelope) on S3, streamed bytes otherwise."""
    artifact_id = request.path_params["artifact_id"]
    if not looks_like_uuid(artifact_id):
        return json_error("Artifact not found", 404)
    decoded, error = await authenticate(request)
    if error is not None:
        return error
    bind_log_context("artifact_download", decoded.get("sub") if decoded else None)
    query = request.query_params

    try:
        version_row, failure = await anyio.to_thread.run_sync(
            _load_version, artifact_id, decoded, query
        )
        if failure is not None:
            return json_error(*failure)

        # The object key is derived only from the stored path, never client input.
        storage_path = version_row.get("storage_path")
        if not storage_path:
            return json_error("No file for this version", 404)

        mime_type = version_row.get("mime_type") or "application/octet-stream"
        storage = await anyio.to_thread.run_sync(StorageCreator.get_storage)

        # With URL_STRATEGY=="s3" the contract is to hand back a presigned
        # URL. If the active backend can't mint one, that's a config error:
        # surface a 500 rather than silently proxying bytes from a backend
        # the operator expected to be off the hot path.
        if getattr(settings, "URL_STRATEGY", "backend") == "s3":
            try:
                url = await anyio.to_thread.run_sync(
                    partial(storage.generate_presigned_url, storage_path, expires_in=_PRESIGNED_URL_TTL)
                )
            except NotImplementedError:
                logger.error(
                    "URL_STRATEGY=s3 but %s cannot mint presigned URLs",
                    type(storage).__name__,
                )
                return json_error("Storage misconfigured", 500)
            # A 302 to a cross-origin S3 URL can't be read by the app's authed
            # fetch (the bucket has no CORS grant for the app origin). When the
            # client opts in via ?disposition=url (or Accept: application/json)
            # hand the presigned URL back as JSON so it can navigate to it
            # top-level (no CORS). Default stays a 302 so nothing else breaks.
            if query.get("disposition") == "url" or (
                "application/json" in request.headers.get("Accept", "")
            ):
                # Tag the envelope with a distinctive media type so the client
                # keys off a server-set signal, not the JSON body shape. A
                # ``data`` artifact whose bytes happen to be
                # ``{"success":true,"url":"..."}`` is streamed under the backend
                # strategy with its own content-type and can never carry this
                # vendor type, so it can't be mistaken for a redirect
                # (open-redirect gadget). Content-Type is CORS-safelisted.
                return JSONResponse(
                    {"success": True, "url": url}, media_type=_ARTIFACT_URL_ENVELOPE_MIME
                )
            return RedirectResponse(url, status_code=302)

        # Build the headers before opening the file, so nothing between the
        # open and the response can fail and leave the handle unclosed.
        headers = {"Content-Disposition": _content_disposition(version_row.get("filename"), artifact_id)}
        # Stream the bytes in chunks instead of buffering the whole object in
        # memory (artifacts can be many MB); the handle closes when the
        # response ends, including on a client disconnect.
        file_obj = await anyio.to_thread.run_sync(storage.get_file, storage_path)
        return ClosingStreamingResponse(
            _read_chunks(file_obj),
            media_type=mime_type,
            headers=headers,
            on_close=partial(_close_file, file_obj),
        )
    except FileNotFoundError:
        return json_error("File not found", 404)
    except Exception:
        logger.error("Error downloading artifact %s", artifact_id, exc_info=True)
        return JSONResponse({"success": False}, status_code=400)


# Mounted in ``docsgpt/asgi.py`` ahead of the Flask catch-all. The other
# artifact routes stay on Flask (``routes.py``).
artifact_download_routes = [
    Route("/api/artifacts/{artifact_id}/download", download_artifact, methods=["GET"]),
]
