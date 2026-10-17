"""Filenames for attachments that arrive without a trustworthy name.

A ``/v1`` client names a file part whatever it likes (``PRILOGA_1.PDF``) or
not at all (an image data URL). Parsers are chosen by extension and the
OpenAI Files API refuses an upper-case one ("Expected context stuffing file
type ... but got .PDF"), so every such name is reduced to its base name with
a lower-case extension, and given one from the MIME type when it has none.
"""

from __future__ import annotations

import mimetypes
import os
from typing import Optional

# Extensions ``mimetypes`` guesses differently across platforms.
_PREFERRED_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def extension_for_mime(mime_type: Optional[str]) -> str:
    """The usual extension of ``mime_type``, or ``""`` when unknown.

    Args:
        mime_type: A MIME type such as ``application/pdf``.

    Returns:
        A lower-case extension with its dot.
    """
    if not mime_type:
        return ""
    mime_type = mime_type.split(";", 1)[0].strip().lower()
    return _PREFERRED_EXTENSIONS.get(mime_type) or (mimetypes.guess_extension(mime_type) or "")


def normalize_attachment_filename(
    filename: Optional[str], mime_type: Optional[str] = None, *, stem: str = "attachment"
) -> str:
    """A safe base name with a lower-case extension.

    Args:
        filename: The name the client sent, possibly a path or None.
        mime_type: The file's MIME type, for a name with no extension.
        stem: Name to use when the client sent none.

    Returns:
        The normalized filename.
    """
    base = os.path.basename(str(filename or "").replace("\\", "/")).strip()
    name, extension = os.path.splitext(base)
    if not name:
        name, extension = stem, ""
    extension = extension.lower() or extension_for_mime(mime_type)
    return f"{name}{extension}"
