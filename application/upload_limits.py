"""Bound user-controlled upload streams before storage or parsing."""

from __future__ import annotations

import io
import os
from typing import BinaryIO

from application.core.settings import settings


_COPY_CHUNK_BYTES = 64 * 1024
_DOCUMENT_UPLOAD_PATHS = frozenset(
    {
        "/api/upload",
        "/api/manage_source_files",
        "/api/store_attachment",
        "/api/parse_spec",
        "/api/create_agent",
    }
)


class UploadTooLargeError(ValueError):
    """Raised when one uploaded file exceeds the configured byte cap."""


class _LimitedRawReader(io.RawIOBase):
    """Expose a binary stream while enforcing an exact cumulative read cap."""

    def __init__(self, stream: BinaryIO, max_bytes: int) -> None:
        super().__init__()
        self._stream = stream
        self._max_bytes = max_bytes
        self._bytes_read = 0

    def readable(self) -> bool:
        """Return whether this wrapper supports reads."""
        return True

    def readinto(self, buffer: bytearray) -> int:
        """Read one bounded chunk into ``buffer``."""
        remaining_with_probe = self._max_bytes - self._bytes_read + 1
        chunk = self._stream.read(min(len(buffer), remaining_with_probe))
        if not chunk:
            return 0
        self._bytes_read += len(chunk)
        if self._bytes_read > self._max_bytes:
            raise UploadTooLargeError(upload_limit_message(self._max_bytes))
        buffer[: len(chunk)] = chunk
        return len(chunk)


def is_document_upload_path(path: str) -> bool:
    """Return whether a route accepts a user-controlled document/image file."""
    return path in _DOCUMENT_UPLOAD_PATHS or path.startswith("/api/update_agent/")


def upload_limit_message(max_bytes: int | None = None) -> str:
    """Return the stable client-facing file-size rejection message."""
    limit = int(max_bytes or settings.UPLOAD_MAX_FILE_BYTES)
    return f"File exceeds the {limit}-byte upload limit"


def upload_request_limit_message(max_bytes: int | None = None) -> str:
    """Return the stable client-facing request-size rejection message."""
    limit = int(max_bytes or settings.UPLOAD_MAX_REQUEST_BYTES)
    return f"Request exceeds the {limit}-byte upload limit"


def copy_upload_to_path(
    upload: BinaryIO,
    destination: str | os.PathLike[str],
    max_bytes: int | None = None,
) -> int:
    """Copy an upload to disk while enforcing a hard streaming byte limit.

    The limit is checked during reads, so it does not rely on a trustworthy
    ``Content-Length`` header or on the input stream being seekable.
    """
    limit = int(max_bytes or settings.UPLOAD_MAX_FILE_BYTES)
    stream = getattr(upload, "stream", upload)
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass

    total = 0
    with open(destination, "wb") as target:
        while True:
            chunk = stream.read(min(_COPY_CHUNK_BYTES, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise UploadTooLargeError(upload_limit_message(limit))
            target.write(chunk)
    return total


def read_upload_limited(upload: BinaryIO, max_bytes: int | None = None) -> bytes:
    """Read at most one configured file into memory, rejecting overflow."""
    limit = int(max_bytes or settings.UPLOAD_MAX_FILE_BYTES)
    stream = getattr(upload, "stream", upload)
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass
    data = bytearray()
    while True:
        chunk = stream.read(min(_COPY_CHUNK_BYTES, limit - len(data) + 1))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise UploadTooLargeError(upload_limit_message(limit))
    return bytes(data)


def read_text_upload_limited(
    upload: BinaryIO,
    max_bytes: int | None = None,
    encoding: str = "utf-8",
) -> str:
    """Decode a bounded upload without first duplicating it into ``bytes``."""
    limit = int(max_bytes or settings.UPLOAD_MAX_FILE_BYTES)
    stream = getattr(upload, "stream", upload)
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass

    raw_reader = _LimitedRawReader(stream, limit)
    buffered_reader = io.BufferedReader(raw_reader, buffer_size=_COPY_CHUNK_BYTES)
    text_reader = io.TextIOWrapper(buffered_reader, encoding=encoding)
    try:
        return text_reader.read()
    finally:
        try:
            text_reader.detach()
        except (ValueError, OSError):
            pass
        try:
            buffered_reader.detach()
        except (ValueError, OSError):
            pass
