"""Tests for the shared file-extension constants."""

import re
from importlib.util import find_spec
from pathlib import Path

import pytest

from application.parser.file.bulk import get_default_file_extractor
from application.parser.file.constants import (
    ATTACHMENT_PARSER_EXTENSIONS,
    attachment_extension,
    has_attachment_parser,
    SUPPORTED_SOURCE_EXTENSIONS,
)

FRONTEND_CONSTANTS = (
    Path(__file__).resolve().parents[3] / "frontend/src/constants/fileUpload.ts"
)


@pytest.mark.unit
def test_parser_extensions_match_the_extractor():
    """The list is a hand-kept literal; this is what keeps it honest.

    ``ATTACHMENT_PARSER_EXTENSIONS`` cannot import the extractor (that would
    pull docling into the API process), so a parser added to
    ``get_default_file_extractor`` would otherwise stay refused as an
    attachment — which is how .webp, .tiff, .vtt and .xml were first missed.
    A suffix listed here but *without* a parser is the opposite failure: it
    skips the content check and reaches the plain-text fallthrough, which is
    how a binary named notes.txt got through.
    """
    parser_suffixes = set(get_default_file_extractor())

    assert parser_suffixes <= set(ATTACHMENT_PARSER_EXTENSIONS), (
        "parsers exist for suffixes the attachment gate refuses: "
        f"{sorted(parser_suffixes - set(ATTACHMENT_PARSER_EXTENSIONS))}"
    )
    if find_spec("docling") is not None:
        assert parser_suffixes == set(ATTACHMENT_PARSER_EXTENSIONS), (
            "listed as parser-backed but nothing parses them: "
            f"{sorted(set(ATTACHMENT_PARSER_EXTENSIONS) - parser_suffixes)}"
        )


@pytest.mark.unit
def test_frontend_mirrors_the_parser_extensions():
    """The composer gates uploads client-side; a divergent list refuses valid files.

    ``ATTACHMENT_PARSER_EXTENSIONS`` in the frontend is a hand-kept copy of
    the backend's. Nothing but this test connects them, and .mdx, .xhtml and
    .adoc were blocked in the UI while the API accepted them before it
    existed.
    """
    if not FRONTEND_CONSTANTS.exists():
        pytest.skip("frontend sources not present in this checkout")

    source = FRONTEND_CONSTANTS.read_text(encoding="utf-8")
    match = re.search(
        r"ATTACHMENT_PARSER_EXTENSIONS:\s*readonly string\[\]\s*=\s*\[(.*?)\]",
        source,
        re.DOTALL,
    )
    assert match, "ATTACHMENT_PARSER_EXTENSIONS not found in fileUpload.ts"
    frontend_extensions = set(re.findall(r"'(\.[^']+)'", match.group(1)))

    assert frontend_extensions == set(ATTACHMENT_PARSER_EXTENSIONS), (
        "frontend and backend attachment lists disagree — "
        f"backend only: {sorted(set(ATTACHMENT_PARSER_EXTENSIONS) - frontend_extensions)}, "
        f"frontend only: {sorted(frontend_extensions - set(ATTACHMENT_PARSER_EXTENSIONS))}"
    )


@pytest.mark.unit
def test_source_ingestion_types_are_parser_backed_apart_from_text():
    """Source ingestion's own list must not smuggle a parserless suffix past the sniff."""
    assert set(SUPPORTED_SOURCE_EXTENSIONS) - set(ATTACHMENT_PARSER_EXTENSIONS) == {
        ".txt"
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Photo.JPG", ".jpg"),
        ("/tmp/dir.d/report.PDF", ".pdf"),
        ("archive.tar.gz", ".gz"),
        ("Dockerfile", ""),
        (".env", ""),
        ("trailing.", "."),
        (None, ""),
    ],
)
def test_attachment_extension(filename, expected):
    assert attachment_extension(filename) == expected


@pytest.mark.unit
def test_has_attachment_parser_is_case_insensitive_and_excludes_zip():
    assert has_attachment_parser("Report.PDF")
    assert has_attachment_parser("scan.WebP")
    # No parser: admitted (or not) on content instead, never on the suffix.
    assert not has_attachment_parser("archive.zip")
    assert not has_attachment_parser("main.py")
    assert not has_attachment_parser("clip.mp4")
    # .txt is the plain-text fallthrough itself, not a parser.
    assert not has_attachment_parser("notes.txt")
