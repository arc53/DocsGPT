"""HTML parsers.

``HTMLParser`` returns the visible text of a page (the ``fast`` engine and
the legacy no-docling map rely on that plain-text contract).
``HTMLMarkdownParser`` returns Markdown instead and is what the anydoc
engine maps ``.html``/``.xhtml`` to: anydoc has no HTML support, and
markdownify — already a dependency of the web crawler — keeps links, GFM
tables, headings and byte-exact code blocks at a few ms per page.
"""
import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from application.core.settings import settings
from application.parser.file.base_parser import BaseParser
from application.utils import truncate_to_line_boundary

logger = logging.getLogger(__name__)

# The crawler's conventions (``crawler_markdown.py`` / ``read_webpage.py``),
# so file and web ingestion produce the same Markdown shape.
MARKDOWNIFY_OPTIONS = {"heading_style": "ATX", "newline_style": "BACKSLASH"}

# Elements whose text is never document content. ``title`` is reported via
# ``get_file_metadata`` instead of leaking in as a stray first line.
_DROP_TAGS = ("title", "script", "style", "noscript", "template")


def html_to_markdown(html: Union[str, bytes]) -> str:
    """Convert an HTML/XHTML document to Markdown.

    Args:
        html: The markup. Pass the raw bytes when you have them: BeautifulSoup
            then decodes by the document's own BOM / ``<meta charset>``
            instead of the process locale, so a windows-1250 page keeps its
            diacritics.

    Returns:
        Markdown with runs of blank lines collapsed to one.
    """
    from bs4 import BeautifulSoup

    return soup_to_markdown(BeautifulSoup(html, "html.parser"))


def soup_to_markdown(soup) -> str:
    """Convert a parsed ``BeautifulSoup`` tree to Markdown.

    Destructive: the non-content elements in ``_DROP_TAGS`` (including
    ``<title>``) are removed from ``soup``; read the title first.

    Args:
        soup: The parsed document.

    Returns:
        Markdown with runs of blank lines collapsed to one.
    """
    from markdownify import MarkdownConverter

    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    markdown = MarkdownConverter(**MARKDOWNIFY_OPTIONS).convert_soup(soup)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def _soup_title(soup) -> Optional[str]:
    """The document's ``<title>`` text, or None."""
    if soup.title and soup.title.string:
        return str(soup.title.string)
    return None


def _trim_torn_utf8_tail(data: bytes) -> bytes:
    """Drop a trailing partial multi-byte UTF-8 sequence left by a byte cut.

    A cut that lands inside a multi-byte character matters more than one
    lost glyph: BeautifulSoup decodes strictly and, when the declared UTF-8
    fails on the torn tail, retries as windows-1252 — and if every other
    non-ASCII byte happens to be cp1252-valid (German umlauts are), the
    *whole* document comes back as mojibake. Only a UTF-8 tail is
    recognised; a single-byte page loses at most the final byte.

    Args:
        data: A head window whose last bytes may be a torn sequence.

    Returns:
        ``data`` minus any trailing incomplete UTF-8 sequence.
    """
    end = len(data)
    trailing = 0
    while end > 0 and trailing < 3 and 0x80 <= data[end - 1] < 0xC0:
        end -= 1
        trailing += 1
    if end == 0:
        return data
    lead = data[end - 1]
    if lead < 0xC0:
        return data
    need = 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4
    if trailing + 1 < need:
        return data[: end - 1]
    return data


def read_markup_head(file: Path, max_bytes: int) -> bytes:
    """Read a markup file, head-truncated to ``max_bytes`` on a line boundary.

    HTML has no lightweight fallback parser to bound it by other means (the
    way oversized CSV/XLSX go to the plain tabular parsers), and the soup +
    markdownify tree costs ~50x the input — 30 MB measured at 1.6 GB RSS,
    against a 100 MB upload cap. Parsing only the head keeps one upload from
    taking the ingest worker down; the cut lands on a line boundary when one
    is reasonably close, and the lenient HTML parser copes with the torn tail.

    Args:
        file: Path to the markup file.
        max_bytes: Size gate; ``<= 0`` reads the whole file.

    Returns:
        The file's bytes, or its first ``max_bytes`` when it is larger.
    """
    with open(file, "rb") as fh:
        if max_bytes <= 0:
            return fh.read()
        head = fh.read(max_bytes + 1)
    if len(head) <= max_bytes:
        return head
    logger.warning(
        f"Markup {Path(file).name} exceeds MARKUP_MAX_BYTES ({max_bytes}); "
        f"parsing the first {max_bytes} bytes to bound memory"
    )
    return _trim_torn_utf8_tail(truncate_to_line_boundary(head[:max_bytes]))


class HTMLParser(BaseParser):
    """HTML parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        """Extract the visible text of an HTML file.

        Returns the text as a string, matching the other file parsers — the
        title is recovered separately by ``get_file_metadata``.
        """
        from bs4 import BeautifulSoup

        with open(file, "r", errors=errors) as f:
            soup = BeautifulSoup(f, "html.parser")
        return soup.get_text("\n")

    def get_file_metadata(self, file: Path) -> Dict:
        """Return the document title, when the markup carries one."""
        from bs4 import BeautifulSoup

        try:
            with open(file, "r", errors="ignore") as f:
                soup = BeautifulSoup(f, "html.parser")
        except OSError:
            return {}
        if soup.title and soup.title.string:
            return {"title": str(soup.title.string)}
        return {}


class HTMLMarkdownParser(HTMLParser):
    """HTML/XHTML to Markdown, for chunking and retrieval.

    Differs from ``HTMLParser`` in three ways: the body comes back as
    Markdown; the file is read as bytes so the document's own charset
    declaration wins over the process locale; and input is head-truncated at
    ``MARKUP_MAX_BYTES`` (the docling HTML path has the same gate under
    ``DOCLING_MARKUP_MAX_BYTES``).
    """

    def __init__(self, parser_config: Optional[Dict] = None) -> None:
        super().__init__(parser_config)
        # (path, title) of the most recent ``parse_file``, so the metadata
        # call that follows it does not build the soup a second time.
        self._last_title: Optional[Tuple[Path, Optional[str]]] = None

    @staticmethod
    def _read(file: Path) -> bytes:
        return read_markup_head(Path(file), int(settings.MARKUP_MAX_BYTES))

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        """Convert an HTML file to Markdown.

        ``errors`` is accepted for the ``BaseParser`` contract but unused:
        decoding is done by BeautifulSoup from the raw bytes.
        """
        from bs4 import BeautifulSoup

        _ = errors
        soup = BeautifulSoup(self._read(file), "html.parser")
        self._last_title = (Path(file), _soup_title(soup))
        return soup_to_markdown(soup)

    def get_file_metadata(self, file: Path) -> Dict:
        """Return the document title, decoded the same way as the body."""
        from bs4 import BeautifulSoup

        last = self._last_title
        if last is not None and last[0] == Path(file):
            title = last[1]
        else:
            try:
                title = _soup_title(BeautifulSoup(self._read(file), "html.parser"))
            except OSError:
                return {}
        return {"title": title} if title else {}
