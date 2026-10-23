"""Web page → Markdown of its main content, shared by the web loaders.

The page loaders (``url``, ``crawler``, ``sitemap``) used to store
``get_text()`` of the whole page, so every page's first chunk repeated the
site's header, menu and footer, and headings were lost. This keeps the page's
main content and converts it with the same Markdown conventions as uploaded
HTML (``html_parser.soup_to_markdown``).

Links keep their text. Their URLs are dropped by default: measured on ten
real pages, URLs in the chunk text added up to 40% tokens and ranked answers
lower. ``keep_links`` keeps them for links inside sentences only; menus and
lists of bare links never carry them.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, Optional, Union
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter

from docsgpt.core.settings import settings
from docsgpt.parser.file.html_parser import MARKDOWNIFY_OPTIONS, cap_markup_bytes, soup_to_markdown
from docsgpt.parser.remote.base import url_to_virtual_path
from docsgpt.parser.schema.base import Document
from docsgpt.security.safe_url import pinned_fetch_bytes

logger = logging.getLogger(__name__)

# The most of one page a fetch reads when MARKUP_MAX_BYTES is off (0): the
# gate keeps the parser bounded, this keeps the download bounded.
_PAGE_CEILING_BYTES = 50 * 1024 * 1024


def page_fetch_bytes() -> int:
    """How much of a page body a fetch reads.

    One byte over ``MARKUP_MAX_BYTES``, so ``cap_markup_bytes`` still sees
    the page as too large, cuts it on a line and logs it.

    Returns:
        The byte ceiling to pass to ``fetch_page``.
    """
    cap = int(settings.MARKUP_MAX_BYTES)
    return cap + 1 if cap > 0 else _PAGE_CEILING_BYTES


def fetch_page(
    url: str,
    max_bytes: Optional[int] = None,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    truncate: bool = True,
) -> requests.Response:
    """GET ``url`` through the SSRF-pinned fetcher, reading at most ``max_bytes``.

    The body is streamed and counted after Content-Encoding is undone, so a
    gzip bomb or a server that never stops sending can't exhaust memory.

    Args:
        url: The address to fetch.
        max_bytes: The byte ceiling; ``None`` for a page's (``page_fetch_bytes``).
        headers: Extra request headers.
        timeout: Seconds per connect and read.
        truncate: Keep the first ``max_bytes`` of a larger body; ``False``
            raises ``ResponseTooLargeError`` instead.

    Returns:
        The response, its ``content`` the capped body. An error status has an
        empty body; call ``raise_for_status`` as usual.

    Raises:
        UnsafeUserUrlError: If the URL fails the SSRF guard.
        ResponseTooLargeError: If the body is too large and ``truncate`` is off.
        requests.RequestException: For network failures.
    """
    body, response = pinned_fetch_bytes(
        url,
        max_bytes=page_fetch_bytes() if max_bytes is None else max_bytes,
        headers=headers,
        timeout=timeout,
        truncate=truncate,
    )
    # The stream is spent and closed; hand the capped body back as the
    # response's content, so callers read ``content`` and ``text`` as usual.
    response._content = body
    return response


class FetchBudget:
    """Fetches one load may still make, shared by every loader it runs."""

    def __init__(self, limit: int):
        """
        Args:
            limit: How many fetches the load may make in all.
        """
        self.remaining = max(0, int(limit))

    def take(self) -> bool:
        """Spend one fetch.

        Returns:
            False, spending nothing, when the budget is used up.
        """
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True

# Site chrome: never the page's content.
_CHROME_TAGS = [
    "script", "style", "noscript", "template", "svg", "iframe", "form", "button", "select",
    "nav", "footer",
]
_CHROME_ROLES = ["navigation", "banner", "contentinfo", "search"]
# Heading permalinks ("¶", "#") and edit links.
_ANCHOR_SELECTORS = "a.headerlink, a.anchor, a.hash-link, a[aria-hidden=true], .mw-editsection"
# Elements whose text a link must fill on its own to count as a bare link.
_TEXT_BLOCKS = ["p", "li", "td", "th", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "figcaption"]

# A root holding less than this share of the page's text is a wrapper, not the content.
_MIN_ROOT_SHARE = 0.25
# An extract below this share of the root's text means the stripping ate the
# content (a JS app, content inside a <form>); the page keeps its plain text.
_MIN_EXTRACT_SHARE = 0.3
# An aside with at least this share of its text in links is a menu; a lower
# one is a footnote or callout and stays.
_ASIDE_LINK_SHARE = 0.6


@dataclass
class PageContent:
    """A page's main content and what the citation needs about it."""

    text: str
    title: Optional[str]
    language: Optional[str]


class _LinkConverter(MarkdownConverter):
    """Markdown with link URLs dropped, or kept only for links inside sentences."""

    def __init__(self, base_url: str, keep_links: bool):
        # Identifiers like ensure_ascii and MAX_TOKENS must stay searchable.
        super().__init__(**MARKDOWNIFY_OPTIONS, escape_underscores=False, escape_asterisks=False, escape_misc=False)
        self.base_url = base_url
        self.keep_links = keep_links

    def convert_a(self, el, text, *args, **kwargs):
        text = (text or "").strip()
        if not text:
            return ""
        if not self.keep_links or _is_bare_link(el):
            return text
        href = (el.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return text
        url = urljoin(self.base_url, href)
        if urlparse(url).scheme not in ("http", "https"):
            return text
        return f"[{text}]({url})"


def _is_bare_link(link) -> bool:
    """Whether a link is the whole text of its block (a menu item, a card, a TOC entry)."""
    block = link.find_parent(_TEXT_BLOCKS)
    if block is None:
        return True
    return block.get_text(" ", strip=True) == link.get_text(" ", strip=True)


def _text_length(element) -> int:
    return len(element.get_text(" ", strip=True))


def _pick_root(soup):
    """The page's main content element: a single ``main``/``article``, else ``body``."""
    body = soup.body or soup
    total = _text_length(body)
    for selector in ("main", "[role=main]", "article"):
        found = soup.select(selector)
        if len(found) == 1 and total and _text_length(found[0]) / total >= _MIN_ROOT_SHARE:
            return found[0]
    return body


def _strip_chrome(root) -> None:
    for tag in root.find_all(_CHROME_TAGS):
        tag.decompose()
    for role in _CHROME_ROLES:
        for tag in root.select(f"[role={role}]"):
            tag.decompose()
    # A page-level header is site chrome; an article's own header holds its title.
    for tag in root.find_all("header"):
        if not tag.find_parent(["article", "main"]):
            tag.decompose()
    for tag in root.find_all("aside") + root.select("[role=complementary]"):
        if tag.decomposed:
            continue
        total = _text_length(tag)
        linked = sum(_text_length(a) for a in tag.find_all("a"))
        if total == 0 or linked / total >= _ASIDE_LINK_SHARE:
            tag.decompose()
    for tag in root.select(_ANCHOR_SELECTORS):
        tag.decompose()


def _images_to_alt_text(root) -> None:
    for img in root.find_all("img"):
        alt = (img.get("alt") or "").strip()
        img.replace_with(NavigableString(alt))


def _listify_link_runs(soup, root) -> None:
    """Turn runs of adjacent links (card grids, tag lists) into a list.

    With no text between them, markdownify glues their labels into one word
    ("QuickstartConcepts").
    """
    for parent in [root, *root.find_all(True)]:
        run = []
        runs = []
        for child in list(parent.children):
            if getattr(child, "name", None) == "a":
                run.append(child)
            elif isinstance(child, NavigableString) and not child.strip():
                continue
            else:
                if len(run) > 1:
                    runs.append(run)
                run = []
        if len(run) > 1:
            runs.append(run)
        for links in runs:
            listing = soup.new_tag("ul")
            links[0].insert_before(listing)
            for link in links:
                item = soup.new_tag("li")
                listing.append(item)
                item.append(link.extract())


def _first_heading(root) -> Optional[str]:
    heading = root.find("h1")
    text = heading.get_text(" ", strip=True) if heading else ""
    return text or None


def extract_page(html: Union[str, bytes], url: str, keep_links: bool = False) -> PageContent:
    """Extract a page's main content as Markdown.

    Args:
        html: The page. Pass bytes when you have them: BeautifulSoup then reads
            the charset from the page itself (a header-less page was decoded
            wrongly as text).
        url: The page's address, for resolving relative links.
        keep_links: Keep the URL of links that sit inside a sentence.

    Returns:
        The Markdown, the ``<title>`` (else the first heading) and the
        ``lang`` attribute. When the extract is near-empty against the page's
        text, the text is the page's plain text instead.
    """
    if isinstance(html, bytes):
        html = cap_markup_bytes(html, int(settings.MARKUP_MAX_BYTES), url)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    language = (soup.html.get("lang") if soup.html else None) or None
    root = _pick_root(soup)
    title = title or _first_heading(root)
    plain = root.get_text("\n", strip=True)

    _strip_chrome(root)
    _images_to_alt_text(root)
    _listify_link_runs(soup, root)
    markdown = soup_to_markdown(root, converter=_LinkConverter(url, keep_links))

    if len(markdown) < _MIN_EXTRACT_SHARE * len(plain):
        logger.info(f"Page extract of {url} is near-empty ({len(markdown)} of {len(plain)} chars); keeping plain text")
        markdown = re.sub(r"\n{3,}", "\n\n", plain)
    return PageContent(text=markdown, title=title or None, language=language)


# Text a page address may serve instead of HTML (llms.txt, a raw README), kept
# as written. JSON counts only for a page added by address: there it was asked
# for, while a crawl or sitemap reaching JSON has hit an API or a feed.
_PLAIN_TEXT_TYPES = ("text/plain", "text/markdown", "text/x-markdown")
_ATX_TITLE = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _media_type(content_type: Optional[str]) -> str:
    """The bare, lower-case media type of a ``Content-Type`` header."""
    return (content_type or "").split(";")[0].strip().lower()


def is_html(content_type: Optional[str]) -> bool:
    """Whether a response is an HTML page (and so may hold links to follow).

    Args:
        content_type: The response's ``Content-Type``; ``None`` is taken as HTML.

    Returns:
        True for HTML and XHTML.
    """
    if not content_type:
        return True
    media = _media_type(content_type)
    return media in ("text/html", "application/xhtml+xml") or media.endswith("+html")


def _is_plain_text(content_type: Optional[str], explicit: bool) -> bool:
    """Whether a non-HTML response is text to keep as written."""
    media = _media_type(content_type)
    if media in _PLAIN_TEXT_TYPES:
        return True
    return explicit and (media == "application/json" or media.endswith("+json"))


def _decode_text(body: Union[str, bytes], content_type: Optional[str], url: str) -> str:
    """Size-cap and decode a plain-text body by its declared charset (UTF-8 otherwise).

    Args:
        body: The response body.
        content_type: The ``Content-Type``, for its ``charset``.
        url: The address, for the size warning.

    Returns:
        The text, cut at ``MARKUP_MAX_BYTES`` on a line boundary.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    body = cap_markup_bytes(body, int(settings.MARKUP_MAX_BYTES), url)
    match = re.search(r"charset\s*=\s*\"?([\w.:-]+)", content_type or "", re.IGNORECASE)
    try:
        return body.decode(match.group(1) if match else "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def page_document(
    body: Union[str, bytes],
    content_type: Optional[str],
    url: str,
    include_host: bool = False,
    keep_links: bool = False,
    explicit: bool = False,
) -> Optional[Document]:
    """Build the ingest ``Document`` for a fetched page.

    Args:
        body: The response body (bytes preferred, see ``extract_page``).
        content_type: The response's ``Content-Type``; ``None`` is taken as HTML.
        url: The page's address, stored as ``source``.
        include_host: Prefix the host in ``file_path`` (an ingest spanning hosts).
        keep_links: Keep the URL of links inside sentences.
        explicit: The page was added by its address, not found by a crawl or
            sitemap; JSON is then kept as text too.

    Returns:
        The document, or ``None`` for a binary response (a PDF or image a
        sitemap or crawl reached) or a page with no text. Plain text and
        Markdown are kept as written, titled by their first ``#`` heading.
    """
    if not is_html(content_type):
        if not _is_plain_text(content_type, explicit):
            logger.info(f"Skipping {url}: {content_type} is not a web page")
            return None
        text = _decode_text(body, content_type, url).strip()
        if not text:
            logger.info(f"Skipping {url}: no text")
            return None
        metadata = {"source": url}
        heading = _ATX_TITLE.search(text)
        if heading and _media_type(content_type) in _PLAIN_TEXT_TYPES:
            metadata["title"] = heading.group(1)
        metadata["file_path"] = url_to_virtual_path(url, include_host)
        return Document(text, extra_info=metadata)
    page = extract_page(body, url, keep_links=keep_links)
    if not page.text.strip():
        logger.info(f"Skipping {url}: no text")
        return None
    metadata = {"source": url}
    if page.title:
        metadata["title"] = page.title
    if page.language:
        metadata["language"] = page.language
    # The worker keys the file tree by file_path; the chunks view filters by it.
    metadata["file_path"] = url_to_virtual_path(url, include_host)
    return Document(page.text, extra_info=metadata)
