"""Bound user-controlled upload streams before storage or parsing."""

from __future__ import annotations

import io
import os
from contextlib import suppress
from typing import BinaryIO

from application.core.settings import settings
from application.parser.file.constants import (
    attachment_extension,
    has_attachment_parser,
)


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


class UnsupportedUploadTypeError(ValueError):
    """Raised when an uploaded attachment has a file type the worker cannot parse."""


_UNSUPPORTED_UPLOAD_PREFIX = "Unsupported file type"


def unsupported_upload_message(filename: str | None) -> str:
    """Return the stable client-facing rejection message for an unparseable upload.

    Args:
        filename: The rejected upload's filename.

    Returns:
        ``"Unsupported file type: .mp4"`` style text, naming the extension.
    """
    extension = attachment_extension(filename)
    return f"{_UNSUPPORTED_UPLOAD_PREFIX}: {extension or '(no extension)'}"


def is_unsupported_upload_message(message: str | None) -> bool:
    """Return whether ``message`` is one produced by :func:`unsupported_upload_message`."""
    return bool(message) and str(message).startswith(_UNSUPPORTED_UPLOAD_PREFIX)


# A suffix with no parser is read by ``SimpleDirectoryReader``'s plain-text
# fallthrough, so it is admitted on content: enough of the head to recognise a
# container header, and a tolerance that keeps real text (UTF-8 accents, an
# ANSI-coloured log) in while a random binary — ~12.5% of bytes below 0x20 —
# stays out.
_TEXT_SNIFF_BYTES = 8192
_MAX_NONTEXT_RATIO = 0.10
# Control bytes that occur in ordinary text: tab, LF, VT, FF, CR, ESC.
_TEXT_CONTROL_BYTES = frozenset({0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1B})
# A UTF-16/32 file is half NUL bytes, so it has to be recognised by its BOM
# before the NUL test — Notepad's "Unicode" .txt is ordinary text.
_TEXT_BOMS = (
    b"\xef\xbb\xbf",
    b"\xff\xfe",
    b"\xfe\xff",
    b"\x00\x00\xfe\xff",
)


def looks_like_text(sample: bytes) -> bool:
    """Return whether a leading byte sample reads as text rather than binary.

    Args:
        sample: The first bytes of a file; an empty sample counts as text.

    Returns:
        False when the sample holds a NUL byte or too many other non-text
        control bytes, True otherwise. A Unicode BOM settles it as text.
    """
    if not sample:
        return True
    if sample.startswith(_TEXT_BOMS):
        return True
    if b"\x00" in sample:
        return False
    nontext = sum(
        1
        for byte in sample
        if (byte < 0x20 and byte not in _TEXT_CONTROL_BYTES) or byte == 0x7F
    )
    return nontext / len(sample) <= _MAX_NONTEXT_RATIO


def file_looks_like_text(path: str | os.PathLike[str]) -> bool:
    """Return whether a file on disk reads as text, by its leading bytes.

    Args:
        path: Filesystem path to sample.

    Returns:
        The :func:`looks_like_text` verdict for the file's head; True when the
        file cannot be read, leaving that failure to the parser to report.
    """
    try:
        with open(path, "rb") as handle:
            return looks_like_text(handle.read(_TEXT_SNIFF_BYTES))
    except OSError:
        return True


def enforce_parseable_attachment(
    path: str | os.PathLike[str], filename: str | None
) -> None:
    """Reject an attachment that no parser handles and that is not plain text.

    Suffixes with a parser (``ATTACHMENT_PARSER_EXTENSIONS``) are admitted
    unconditionally — a PDF is binary and parses fine. Everything else, .txt
    included, has to read as text: that is what keeps a video or an archive
    out of the plain-text fallthrough while leaving source, config and log
    files in, whatever the file happens to be named.

    Args:
        path: Local path to the staged upload, readable before it is stored.
        filename: The upload's filename, used for the suffix and the message.

    Raises:
        UnsupportedUploadTypeError: When the file has no parser and its
            contents are binary.
    """
    if has_attachment_parser(filename):
        return
    if file_looks_like_text(path):
        return
    raise UnsupportedUploadTypeError(unsupported_upload_message(filename))


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
    with suppress(AttributeError, OSError):
        stream.seek(0)

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
    with suppress(AttributeError, OSError):
        stream.seek(0)
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
    with suppress(AttributeError, OSError):
        stream.seek(0)

    raw_reader = _LimitedRawReader(stream, limit)
    buffered_reader = io.BufferedReader(raw_reader, buffer_size=_COPY_CHUNK_BYTES)
    text_reader = io.TextIOWrapper(buffered_reader, encoding=encoding)
    try:
        return text_reader.read()
    finally:
        # Cleanup is best effort and must not mask the read result or exception.
        with suppress(ValueError, OSError):
            text_reader.detach()
        with suppress(ValueError, OSError):
            buffered_reader.detach()
