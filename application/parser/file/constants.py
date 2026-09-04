"""Shared file-extension constants for parsing and ingestion flows."""

import os

from application.parser.file.anydoc_parser import ANYDOC_GAINED_SUFFIXES
from application.stt.constants import SUPPORTED_AUDIO_EXTENSIONS


SUPPORTED_SOURCE_DOCUMENT_EXTENSIONS = (
    ".rst",
    ".md",
    ".pdf",
    ".txt",
    ".docx",
    ".csv",
    ".epub",
    ".html",
    ".mdx",
    ".json",
    ".xlsx",
    ".pptx",
    # Read by the HTML parsers on every engine.
    ".xhtml",
    # Read by the anydoc engine (legacy/macro Office, OpenDocument, RTF).
    # Parseable regardless of DOC_PARSER_ENGINE: anydoc is a core dependency,
    # and both parser maps route these suffixes to it.
    *ANYDOC_GAINED_SUFFIXES,
)

SUPPORTED_SOURCE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

SUPPORTED_SOURCE_EXTENSIONS = (
    *SUPPORTED_SOURCE_DOCUMENT_EXTENSIONS,
    *SUPPORTED_SOURCE_IMAGE_EXTENSIONS,
    *SUPPORTED_AUDIO_EXTENSIONS,
)

# Suffixes the attachment path has a dedicated parser for — exactly the keys
# of ``get_default_file_extractor()``. Kept as a literal (importing ``bulk``
# here would drag docling into the API process), with
# ``tests/parser/file/test_constants.py`` asserting the two agree.
#
# This is *not* the whole attachment allow-list: a suffix with no parser is
# read by ``SimpleDirectoryReader``'s plain-text fallthrough, which is right
# for a .py or a .log and catastrophic for a video — the reader "extracts"
# megabytes of binary garbage, truncates it, and stores it with
# ``extraction.status == "ok"``. So unparsed suffixes are admitted on
# content instead (``upload_limits.enforce_parseable_attachment``): text
# passes, binary is refused. Zip is deliberately absent — source ingestion
# extracts archives, the attachment path does not, and a zip fails the
# content check like any other binary.
#
# Mirrored in ``frontend/src/constants/fileUpload.ts``; update both together.
ATTACHMENT_PARSER_EXTENSIONS = frozenset(
    {
        *SUPPORTED_SOURCE_EXTENSIONS,
        ".xhtml",
        ".adoc",
        ".asciidoc",
        ".tiff",
        ".tif",
        ".bmp",
        ".webp",
        ".vtt",
        ".xml",
    }
    # .txt has no parser of its own — it *is* the plain-text fallthrough. It
    # must be sniffed like any other unparsed suffix, or renaming a video to
    # notes.txt walks straight back into the bug this gate exists for.
    - {".txt"}
)


def attachment_extension(filename: str | None) -> str:
    """Return the lower-cased extension of ``filename`` including the dot, or ``""``.

    Args:
        filename: A bare filename or path; ``None`` and empty strings yield ``""``.

    Returns:
        The last suffix in lower case (``".pdf"``), or ``""`` when there is none.
    """
    if not filename:
        return ""
    return os.path.splitext(os.path.basename(str(filename)))[1].lower()


def has_attachment_parser(filename: str | None) -> bool:
    """Return whether an attachment's suffix has a dedicated parser.

    A False result does not mean the file is refused: it means nothing but the
    plain-text fallthrough will read it, so it has to earn its place on
    content. The decision is by extension only, never by the mime type a
    browser reports (mobile pickers ignore ``accept`` and lie).

    Args:
        filename: The upload's filename.

    Returns:
        True when the suffix is in ``ATTACHMENT_PARSER_EXTENSIONS``.
    """
    return attachment_extension(filename) in ATTACHMENT_PARSER_EXTENSIONS
