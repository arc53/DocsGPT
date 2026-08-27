"""Shared file-extension constants for parsing and ingestion flows."""

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
