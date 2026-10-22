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
from typing import Optional, Union
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter

from docsgpt.core.settings import settings
from docsgpt.parser.file.html_parser import MARKDOWNIFY_OPTIONS, cap_markup_bytes, soup_to_markdown
from docsgpt.parser.remote.base import url_to_virtual_path
from docsgpt.parser.schema.base import Document

logger = logging.getLogger(__name__)

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


def _is_html(content_type: Optional[str]) -> bool:
    if not content_type:
        return True
    media = content_type.split(";")[0].strip().lower()
    return media in ("text/html", "application/xhtml+xml") or media.endswith("+html")


def page_document(
    body: Union[str, bytes],
    content_type: Optional[str],
    url: str,
    include_host: bool = False,
    keep_links: bool = False,
) -> Optional[Document]:
    """Build the ingest ``Document`` for a fetched page.

    Args:
        body: The response body (bytes preferred, see ``extract_page``).
        content_type: The response's ``Content-Type``; ``None`` is taken as HTML.
        url: The page's address, stored as ``source``.
        include_host: Prefix the host in ``file_path`` (an ingest spanning hosts).
        keep_links: Keep the URL of links inside sentences.

    Returns:
        The document, or ``None`` for a non-HTML response (a PDF or image a
        sitemap or crawl reached) or a page with no text.
    """
    if not _is_html(content_type):
        logger.info(f"Skipping {url}: {content_type} is not a web page")
        return None
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
