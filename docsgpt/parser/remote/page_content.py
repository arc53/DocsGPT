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

import codecs
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import SplitResult, quote, urldefrag, urljoin, urlparse, urlsplit, urlunsplit

import idna
import requests
from bs4 import BeautifulSoup, CData, Comment, FeatureNotFound, NavigableString, Tag
from markdownify import MarkdownConverter

from docsgpt.core.settings import settings
from docsgpt.parser.file.html_parser import (
    MARKDOWNIFY_OPTIONS,
    MarkupTooDeepError,
    cap_markup_bytes,
    soup_to_markdown,
)
from docsgpt.parser.remote.base import normalize_page_url, url_to_virtual_path
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


# Redirect hops one fetch follows, as browsers and crawlers allow a handful.
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class RedirectError(requests.RequestException):
    """A redirect a fetch won't follow: no ``Location``, a loop, too many hops, or no budget left."""


class CredentialsInUrlError(requests.exceptions.InvalidURL):
    """An address with ``user:password@`` in it, which a fetch won't dial.

    The fetcher would send them as Basic auth, and the page's address (its
    ``source``, shown in citations) would keep the password. Pages behind a
    sign-in aren't read.
    """


def has_userinfo(url: str) -> bool:
    """Whether an address carries ``user[:password]@`` before its host.

    Args:
        url: An address.

    Returns:
        True when its authority has an ``@``; False for one that doesn't
        parse (its fetch fails on its own).
    """
    try:
        return "@" in urlsplit(url).netloc
    except ValueError:
        return False


def without_userinfo(url: str) -> str:
    """An address with any ``user[:password]@`` taken out, for logs and messages.

    Args:
        url: An address.

    Returns:
        The address without its userinfo; unchanged when it has none or doesn't parse.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def _header_text(value: str) -> str:
    """A header value as its sender wrote it: raw UTF-8 bytes read back as UTF-8.

    ``http.client`` reads header bytes as latin-1, so a ``Location`` sent as
    raw UTF-8 (``/café``) arrives as ``/cafÃ©``. Browsers and ``requests``
    read it as UTF-8; a value that isn't UTF-8 stays as it was read.

    Args:
        value: The header value as ``http.client`` decoded it.

    Returns:
        The value re-read as UTF-8, or unchanged when its bytes aren't UTF-8.
    """
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def fetch_page(
    url: str,
    max_bytes: Optional[int] = None,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
    truncate: bool = True,
    budget: Optional["FetchBudget"] = None,
) -> requests.Response:
    """GET ``url`` through the SSRF-pinned fetcher, reading at most ``max_bytes``.

    The body is streamed and counted after Content-Encoding is undone, so a
    gzip bomb or a server that never stops sending can't exhaust memory.

    Redirects are followed by hand, up to ``MAX_REDIRECTS``: each ``Location``
    is made absolute against the address that sent it and fetched through
    the same pinned fetcher, so every hop passes the SSRF guard on its own.
    A 3xx is never returned as content.

    Args:
        url: The address to fetch.
        max_bytes: The byte ceiling; ``None`` for a page's (``page_fetch_bytes``).
        headers: Extra request headers.
        timeout: Seconds per connect and read.
        truncate: Keep the first ``max_bytes`` of a larger body; ``False``
            raises ``ResponseTooLargeError`` instead.
        budget: The load's fetch budget, charged one fetch per redirect hop
            (the caller has paid for the first request).

    Returns:
        The final response, its ``content`` the capped body and its ``url``
        the address that answered (not the dialed IP). An error status has an
        empty body; call ``raise_for_status`` as usual.

    Raises:
        UnsafeUserUrlError: If the URL, or a redirect target, fails the SSRF guard.
        RedirectError: A 3xx without a ``Location``, a redirect loop, more
            than ``MAX_REDIRECTS`` hops, or a spent budget mid-chain.
        CredentialsInUrlError: The URL, or a redirect target, has ``user:password@``.
        ResponseTooLargeError: If the body is too large and ``truncate`` is off.
        requests.RequestException: For network failures.
    """
    if has_userinfo(url):
        raise CredentialsInUrlError(f"{without_userinfo(url)} has credentials in its address; not fetching it")
    current = url
    seen = {url}
    for hop in range(MAX_REDIRECTS + 1):
        body, response = pinned_fetch_bytes(
            current,
            max_bytes=page_fetch_bytes() if max_bytes is None else max_bytes,
            headers=headers,
            timeout=timeout,
            truncate=truncate,
        )
        status = response.status_code
        if not 300 <= status < 400:
            # The stream is spent and closed; hand the capped body back as the
            # response's content, so callers read ``content`` and ``text`` as
            # usual. ``url`` is the pinned IP until it is set to the page's.
            response._content = body
            response.url = current
            return response
        location = _header_text(response.headers.get("Location") or "").strip()
        if status not in _REDIRECT_STATUSES or not location:
            raise RedirectError(f"{current} answered {status} with no redirect to follow")
        if hop == MAX_REDIRECTS:
            raise RedirectError(f"{url} took more than {MAX_REDIRECTS} redirects")
        target = urldefrag(urljoin(current, location))[0]
        if has_userinfo(target):
            raise CredentialsInUrlError(f"{url} redirects to an address with credentials; not following it")
        if target in seen:
            raise RedirectError(f"{url} redirects in a loop at {target}")
        if budget is not None and not budget.take():
            raise RedirectError(f"Fetch budget spent following {url} to {target}")
        seen.add(target)
        current = target
    raise RedirectError(f"{url} took more than {MAX_REDIRECTS} redirects")  # pragma: no cover - loop returns


def final_url(response: Any, requested: str) -> str:
    """The address a fetched page answered from, after redirects.

    Args:
        response: A ``fetch_page`` response.
        requested: The address that was asked for, used when the response
            carries none.

    Returns:
        The final URL.
    """
    url = getattr(response, "url", None)
    return url if isinstance(url, str) and url else requested


def ascii_host(host: Optional[str]) -> str:
    """A host in the lower-case ASCII form a browser's ``new URL()`` gives it.

    A label with non-ASCII characters is mapped (UTS #46, non-transitional:
    ``faß`` stays distinct from ``fass``) and written in punycode, so
    ``bücher.de`` and ``xn--bcher-kva.de`` are one host. An ASCII label is
    only lower-cased, whatever IDNA thinks of it (``a_b`` stays).

    Args:
        host: A host name as ``urlsplit`` reads it.

    Returns:
        The ASCII form; the lower-cased host as given when IDNA refuses it.
    """
    host = host or ""
    if host.isascii():
        return host.lower()
    try:
        mapped = idna.uts46_remap(host, std3_rules=False, transitional=False)
        labels = [label if label.isascii() else idna.alabel(label).decode("ascii") for label in mapped.split(".")]
    except (idna.IDNAError, UnicodeError, ValueError):
        return host.lower()
    return ".".join(labels).lower()


def bare_host(host: Optional[str]) -> str:
    """A host compared case-insensitively in its ASCII form, with ``www.`` treated as the bare host."""
    host = ascii_host(host).rstrip(".")
    return host[4:] if host.startswith("www.") else host


_DEFAULT_PORTS = {"http": 80, "https": 443}


def explicit_port(parts: SplitResult) -> Optional[int]:
    """The port an address names, unless it is its scheme's own (80 for http, 443 for https).

    Args:
        parts: The ``urlsplit`` of an address.

    Returns:
        The port, or ``None`` when there is none or it is the default.

    Raises:
        ValueError: If the port is not a number in range.
    """
    port = parts.port
    return None if port is None or port == _DEFAULT_PORTS.get(parts.scheme) else port


def host_with_port(parts: SplitResult, host: str) -> str:
    """A key's host part: ``host``, plus ``:port`` when the address names a port of its own.

    Args:
        parts: The ``urlsplit`` of an address.
        host: Its host as the key spells it (``bare_host`` or as written).

    Returns:
        ``host`` or ``host:port``; an IPv6 host goes in brackets.

    Raises:
        ValueError: If the port is not a number in range.
    """
    if ":" in host:
        host = f"[{host}]"
    port = explicit_port(parts)
    return host if port is None else f"{host}:{port}"


def _is_dot_segment(segment: str, dots: str) -> bool:
    """Whether a path segment is ``dots`` (``.`` or ``..``), each dot plain or written ``%2e``/``%2E``."""
    return segment.lower().replace("%2e", ".") == dots


def remove_dot_segments(path: str) -> str:
    """A URL path with its ``.`` and ``..`` segments resolved (RFC 3986, 5.2.4).

    Servers resolve them, so ``/docs/../admin`` is ``/admin``; a percent-encoded
    dot (``%2e``) counts too, as many servers decode it first. Only whole
    segments are dots: ``/a..b`` stays. ``..`` never climbs above the root.

    Args:
        path: The path part of a URL.

    Returns:
        The path the server would serve; a dot segment at the end leaves a
        trailing slash (``/a/b/..`` is ``/a/``).
    """
    if "." not in path and "%2" not in path:
        return path
    segments = path.split("/")
    resolved = segments[:1]  # "" for an absolute path: the root is never popped
    for index, segment in enumerate(segments[1:], start=1):
        is_last = index == len(segments) - 1
        if _is_dot_segment(segment, "."):
            pass
        elif _is_dot_segment(segment, ".."):
            if len(resolved) > 1:
                resolved.pop()
        else:
            resolved.append(segment)
            continue
        if is_last:
            resolved.append("")
    return "/".join(resolved) or "/"


# Characters RFC 3986 never needs encoded: ``%41`` is ``A`` to every server.
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PERCENT_TRIPLET = re.compile(r"%([0-9A-Fa-f]{2})")
# Encoded separators: a server may decode them into a path's ``/`` or ``\``.
_ENCODED_SEPARATOR = re.compile(r"%(?:2F|5C)", re.IGNORECASE)


def _encode_char(char: str) -> str:
    """One character as UTF-8 percent triplets; a lone surrogate as U+FFFD, as a browser writes it."""
    if 0xD800 <= ord(char) <= 0xDFFF:
        char = "�"
    return "".join(f"%{byte:02X}" for byte in char.encode("utf-8"))


def normalize_percent_encoding(text: str) -> str:
    """A URL path (or query) in one spelling, however it was percent-encoded.

    Every non-ASCII character, space and control character is percent-encoded
    as UTF-8; then each ``%XX`` that encodes an unreserved character
    (``A-Z a-z 0-9 - . _ ~``) is decoded and every other one gets upper-case
    hex digits. ``%2F`` stays encoded: it is not the path's ``/``. A ``%``
    not followed by two hex digits is left as it is.

    Args:
        text: The path or query, as written.

    Returns:
        ``/caf%C3%A9`` for ``/café``, ``/caf%c3%a9`` and ``/caf%C3%A9`` alike;
        ``/~a`` for ``/%7Ea``.
    """
    text = "".join(_encode_char(char) if ord(char) <= 0x20 or ord(char) >= 0x7F else char for char in text)

    def triplet(match: "re.Match[str]") -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else f"%{match.group(1).upper()}"

    return _PERCENT_TRIPLET.sub(triplet, text)


def normalized_path(path: str) -> str:
    """A key's path: percent-encoding normalised (``normalize_percent_encoding``), then dot segments resolved.

    Args:
        path: The path part of a URL.

    Returns:
        The path the server would serve, in one spelling.
    """
    return remove_dot_segments(normalize_percent_encoding(path))


def is_ambiguous_path(path: str) -> bool:
    """Whether servers could read a path as another one: an encoded ``/`` or ``\\``, or a dot segment.

    Scope and skip checks treat such a path as out of scope rather than
    guess how the server resolves (or decodes) it.

    Args:
        path: The path part of a URL, as written.

    Returns:
        True for ``/docs/..%2Fadmin``, ``/a%5Cb``, ``/docs/./a`` or
        ``/a/%2e%2e/b``; a name with dots in it (``/a..b``) is no dot segment.
    """
    normalized = normalize_percent_encoding(path)
    if _ENCODED_SEPARATOR.search(normalized):
        return True
    return any(segment in (".", "..") for segment in normalized.split("/"))


def page_key(url: str) -> str:
    """One key per page: scheme, ``www.``, fragment, query order, a trailing slash and dot segments don't count.

    A port does, unless it is the scheme's own: ``x.io:8443/a`` is another
    server's page than ``x.io/a`` (and ``x.io:443/a``). The host is compared
    in its ASCII form (``ascii_host``) and the path and query in one
    percent-encoding (``normalize_percent_encoding``), so ``/café`` and
    ``/caf%c3%a9`` are one page.

    Args:
        url: A page URL.

    Returns:
        ``host[:port]/path`` (plus ``?query``), for comparing pages and skip
        rules; ``/docs/../a`` keys as ``/a``, the page a server answers with.

    Raises:
        ValueError: If the URL cannot be parsed.
    """
    parts = urlsplit(normalize_page_url(url.strip()))
    key = f"{host_with_port(parts, bare_host(parts.hostname))}{normalized_path(parts.path).rstrip('/')}"
    return f"{key}?{normalize_percent_encoding(parts.query)}" if parts.query else key


def note_requested_url(document: Document, requested: str) -> None:
    """Record on a web page's document that fetching ``requested`` ended at it.

    ``extra_info["requested_urls"]`` lists, in the order they were met, the
    distinct addresses (by ``page_key``) that led to the page, other than the
    page's own (its ``source``, or another spelling of it, such as ``www.``).
    ``requested_url``, kept for older readers, is its first; with none, it
    is still set to an address the page answered from under another spelling.

    Args:
        document: A web page's document; ``extra_info["source"]`` its address.
        requested: The address that was fetched.
    """
    info = document.extra_info
    urls = info.setdefault("requested_urls", [])
    source = info.get("source") or ""
    if requested == source:
        return
    try:
        requested_key = page_key(requested)
        if requested_key == page_key(source):
            if not urls:
                info.setdefault("requested_url", requested)
            return
        if any(page_key(url) == requested_key for url in urls):
            return
    except ValueError:
        if requested in urls:
            return
    urls.append(requested)
    info["requested_url"] = urls[0]


def merge_requested_urls(kept: Document, duplicate: Document) -> None:
    """Fold the addresses that led to ``duplicate`` (the same page, loaded again) into ``kept``.

    Args:
        kept: The page's document that stays.
        duplicate: A later document of the same page, dropped by the caller.
    """
    kept.extra_info.setdefault("requested_urls", [])
    for requested in duplicate.extra_info.get("requested_urls") or []:
        note_requested_url(kept, requested)


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
_CHROME_TAGS = ["script", "style", "svg", "iframe", "nav", "footer"]
# Controls and hidden markup: removed too, but a page may render its content
# inside one (a whole-page <form>, a JS app's <noscript> or <template>), so
# the near-empty guard measures the page before these go.
_CONTROL_TAGS = ["noscript", "template", "form", "button", "select"]
_CHROME_ROLES = ["navigation", "banner", "contentinfo", "search"]
# Heading permalinks ("¶", "#") and edit links.
_ANCHOR_SELECTORS = "a.headerlink, a.anchor, a.hash-link, a[aria-hidden=true], .mw-editsection"
# Elements that start a block of their own: beside a link run they are
# layout, not the sentence the links sit in.
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "details", "dd", "div", "dl", "dt", "figcaption", "figure",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "summary", "table", "ul",
})
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
        # Each text block's text, read once: a paragraph of a thousand links
        # re-read its whole text per link.
        self._block_text: Dict[int, str] = {}
        # Each element's text block, found once: links nested deep in one
        # block each walked up to it.
        self._block_of: Dict[int, Optional[Tag]] = {}

    def convert_a(self, el, text, *args, **kwargs):
        text = (text or "").strip()
        if not text:
            return ""
        if not self.keep_links or _is_bare_link(el, self._block_text, self._block_of):
            return text
        href = (el.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return text
        url = urljoin(self.base_url, href)
        if urlparse(url).scheme not in ("http", "https"):
            return text
        return f"[{text}]({_link_destination(url)})"


def _link_destination(url: str) -> str:
    """A URL written as a Markdown link destination that nothing in it can end early.

    Whitespace and ``<``/``>`` are percent-encoded; a URL with ``(`` or ``)``
    is wrapped in angle brackets (``[text](<url>)``), since an unbalanced
    parenthesis would close a bare destination.

    Args:
        url: An absolute http(s) URL.

    Returns:
        The destination to put between the link's parentheses.
    """
    url = re.sub(r"[\s<>]", lambda m: quote(m.group(0), safe=""), url)
    return f"<{url}>" if "(" in url or ")" in url else url


def _text_block(link: Tag, memo: Dict[int, Optional[Tag]]) -> Optional[Tag]:
    """The nearest text block (``_TEXT_BLOCKS``) above a link, each ancestor looked at once per tree.

    Args:
        link: The ``<a>`` element.
        memo: By element ``id``, the block at or above it; shared across
            calls on one tree, so links nested deep in a block don't each
            walk up to it.

    Returns:
        The block, or ``None`` when the link sits in none.
    """
    path = []
    node = link.parent
    block = None
    while node is not None:
        if id(node) in memo:
            block = memo[id(node)]
            break
        if node.name in _TEXT_BLOCKS:
            block = node
            break
        path.append(node)
        node = node.parent
    if block is not None:
        memo[id(block)] = block
    # Every element walked through has the block the walk ended at.
    for walked in path:
        memo[id(walked)] = block
    return block


def _is_bare_link(
    link: Tag, block_text: Optional[Dict[int, str]] = None, block_of: Optional[Dict[int, Optional[Tag]]] = None,
) -> bool:
    """Whether a link is the whole text of its block (a menu item, a card, a TOC entry).

    Args:
        link: The ``<a>`` element.
        block_text: Block texts by ``id``, cached for one conversion (the tree
            doesn't change while it is converted); ``None`` reads each anew.
        block_of: Each element's text block by ``id`` (``_text_block``),
            cached for one conversion; ``None`` looks each one up anew.

    Returns:
        True when the link's text is all of its block's text, or it has no block.
    """
    block = link.find_parent(_TEXT_BLOCKS) if block_of is None else _text_block(link, block_of)
    if block is None:
        return True
    if block_text is None:
        return block.get_text(" ", strip=True) == link.get_text(" ", strip=True)
    text = block_text.get(id(block))
    if text is None:
        text = block_text[id(block)] = block.get_text(" ", strip=True)
    return text == link.get_text(" ", strip=True)


def _text_length(element: Tag) -> int:
    """How many characters of visible text an element holds."""
    return len(element.get_text(" ", strip=True))


# The strings ``get_text`` reads inside an ordinary element.
_TEXT_STRINGS = (NavigableString, CData)


def _measure_text(root: Tag) -> Dict[int, Tuple[int, int]]:
    """Every element's ``_text_length`` and the share of it inside links, in one pass.

    Asking each element for its own text re-reads the elements nested in it,
    so a page of nested asides or spans cost time quadratic in its depth.
    This walks the tree once, children before parents.

    Args:
        root: The element whose descendants (and itself) are measured.

    Returns:
        By element ``id``: ``(text length, link text length)``, the second
        the sum of ``_text_length`` of every ``<a>`` inside it (itself too),
        as summing them one by one would count it.
    """
    # By element id: [characters, non-blank strings, link characters].
    sums: Dict[int, List[int]] = {}
    measures: Dict[int, Tuple[int, int]] = {}
    nodes = [root, *root.descendants]
    for node in reversed(nodes):
        parent = node.parent if node is not root else None
        if isinstance(node, Tag):
            chars, count, linked = sums.pop(id(node), (0, 0, 0))
            length = chars + max(count - 1, 0)
            if node.name == "a":
                linked += length
            measures[id(node)] = (length, linked)
        elif type(node) in _TEXT_STRINGS:
            chars, count, linked = len(node.strip()), 1, 0
            if not chars:
                continue
        else:
            continue
        if parent is not None:
            total = sums.setdefault(id(parent), [0, 0, 0])
            total[0] += chars
            total[1] += count
            total[2] += linked
    return measures


def _pick_root(soup: BeautifulSoup) -> Tag:
    """The page's main content element: a single ``main``/``article``, else ``body``."""
    body = soup.body or soup
    total = _text_length(body)
    for selector in ("main", "[role=main]", "article"):
        found = soup.select(selector)
        if len(found) == 1 and total and _text_length(found[0]) / total >= _MIN_ROOT_SHARE:
            return found[0]
    return body


def _has_ancestor(tag: Tag, names: Tuple[str, ...], memo: Dict[int, bool]) -> bool:
    """Whether an element sits inside one named ``names``, each ancestor looked at once per tree.

    Args:
        tag: The element.
        names: Tag names to look for above it.
        memo: Answers by element ``id``, shared across calls on one tree, so
            elements nested thousands deep don't each walk up to the root.

    Returns:
        True when an ancestor's name is in ``names``.
    """
    path = []
    node = tag.parent
    found = False
    while node is not None:
        if id(node) in memo:
            found = memo[id(node)]
            break
        if node.name in names:
            found = True
            break
        path.append(node)
        node = node.parent
    # Every element walked through has the answer of the one the walk ended at.
    for walked in path:
        memo[id(walked)] = found
    return found


def _is_link_list(total: int, linked: int) -> bool:
    """Whether an aside measured ``total`` characters of text, ``linked`` of them in links, is a menu."""
    return total == 0 or linked / total >= _ASIDE_LINK_SHARE


def _strip_chrome(root: Tag) -> None:
    """Remove site chrome in place: scripts, menus, page headers and footers, link-list asides, permalinks.

    Controls (``_CONTROL_TAGS``) are left for ``_strip_controls``.
    """
    for tag in root.find_all(_CHROME_TAGS):
        tag.decompose()
    for role in _CHROME_ROLES:
        for tag in root.select(f"[role={role}]"):
            tag.decompose()
    # A page-level header is site chrome; an article's own header holds its title.
    in_article: Dict[int, bool] = {}
    page_headers = [tag for tag in root.find_all("header") if not _has_ancestor(tag, ("article", "main"), in_article)]
    # Innermost first, so no header is removed after the one around it.
    for tag in reversed(page_headers):
        tag.decompose()
    complementary = {id(tag) for tag in root.select("[role=complementary]")}
    asides = [tag for tag in root.find_all(True) if tag.name == "aside" or id(tag) in complementary]
    if asides:
        # Each aside is judged on the tree as it is before any aside goes, so
        # one measure of the whole tree serves them all. Asking each aside
        # for its text re-read every aside inside it.
        measures = _measure_text(root)
        menus = [tag for tag in asides if _is_link_list(*measures[id(tag)])]
        # Innermost first, so no aside is removed after the one around it
        # (and none needs a ``decomposed`` check, which bs4 answers by
        # searching the subtree for a tag of that name).
        for tag in reversed(menus):
            tag.decompose()
    for tag in root.select(_ANCHOR_SELECTORS):
        tag.decompose()


def _strip_controls(root: Tag) -> None:
    """Remove forms, buttons, selects and ``<noscript>``/``<template>`` markup in place."""
    for tag in root.find_all(_CONTROL_TAGS):
        tag.decompose()


def _images_to_alt_text(root: Tag) -> None:
    """Replace each image with its alt text, in place."""
    for img in root.find_all("img"):
        alt = (img.get("alt") or "").strip()
        img.replace_with(NavigableString(alt))


def _holds_running_text(parent: Tag, measures: Optional[Dict[int, Tuple[int, int]]] = None) -> bool:
    """Whether an element's own children include text: a sentence, not a stack of blocks.

    Args:
        parent: The element whose children are checked.
        measures: ``_measure_text`` of a tree holding ``parent``, so a child's
            text isn't read anew at every level; ``None`` reads it.

    Returns:
        True when a direct child is non-blank text, or an inline element
        (``<code>``, ``<strong>``...) other than a link that holds text.
    """
    for child in parent.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            if child.strip():
                return True
        elif isinstance(child, Tag) and child.name != "a" and child.name not in _BLOCK_TAGS:
            if measures is not None and id(child) in measures:
                has_text = measures[id(child)][0] > 0
            else:
                has_text = bool(child.get_text(strip=True))
            if has_text:
                return True
    return False


def _listify_link_runs(soup: BeautifulSoup, root: Tag) -> None:
    """Turn runs of adjacent links (card grids, tag lists) into a list.

    With no text between them, markdownify glues their labels into one word
    ("QuickstartConcepts"). Links inside running text ("Install with pip
    conda or from source") stay in their sentence, a space put between any
    that touch.
    """
    # Measured once up front: moving links into a list changes no element's text.
    measures = _measure_text(root)
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
        if runs and _holds_running_text(parent, measures):
            for links in runs:
                for link in links[1:]:
                    if getattr(link.previous_sibling, "name", None) == "a":
                        link.insert_before(NavigableString(" "))
            continue
        for links in runs:
            listing = soup.new_tag("ul")
            links[0].insert_before(listing)
            for link in links:
                item = soup.new_tag("li")
                listing.append(item)
                item.append(link.extract())


def _page_title(soup: BeautifulSoup) -> str:
    """The page's ``<title>``: the first one outside inline SVG or MathML, whose titles name an icon.

    Args:
        soup: The parsed page.

    Returns:
        Its text, or ``""`` when the page has none.
    """
    in_graphic: Dict[int, bool] = {}
    for tag in soup.find_all("title"):
        if not _has_ancestor(tag, ("svg", "math"), in_graphic):
            return tag.get_text(strip=True)
    return ""


def _first_heading(root: Tag) -> Optional[str]:
    """The text of the first ``<h1>``, or ``None``."""
    heading = root.find("h1")
    text = heading.get_text(" ", strip=True) if heading else ""
    return text or None


def extract_page(
    html: Union[str, bytes], url: str, keep_links: bool = False, encoding: Optional[str] = None,
) -> PageContent:
    """Extract a page's main content as Markdown.

    Args:
        html: The page. Pass bytes when you have them: BeautifulSoup then reads
            the charset from the page itself (a header-less page was decoded
            wrongly as text).
        url: The page's address, for resolving relative links.
        keep_links: Keep the URL of links that sit inside a sentence.
        encoding: The charset the HTTP ``Content-Type`` declares
            (``header_charset``); it wins over a ``<meta>`` tag, as in browsers.

    Returns:
        The Markdown, the ``<title>`` (else the first heading) and the
        ``lang`` attribute. When the extract is near-empty against the page's
        text without its chrome (the controls stripped after it can hold the
        content), the text is that plain text instead. A page nested too deep
        to convert is parsed again the way browsers close implied end tags
        (``lxml``), and keeps its plain text when that is still too deep.
    """
    if isinstance(html, bytes):
        html = cap_markup_bytes(html, int(settings.MARKUP_MAX_BYTES), url)
    try:
        return _extract(html_soup(html, encoding), url, keep_links, plain_when_too_deep=False)
    except MarkupTooDeepError:
        pass
    # html.parser nests every unclosed <p> or <li> in the one before it, so a
    # long list written the HTML 4 way nests hundreds deep; lxml closes them.
    logger.info(f"Page {url} nests too deep to convert; parsing it again with lxml")
    try:
        soup = html_soup(html, encoding, parser="lxml")
    except FeatureNotFound:
        soup = html_soup(html, encoding)
    return _extract(soup, url, keep_links, plain_when_too_deep=True)


def _extract(soup: BeautifulSoup, url: str, keep_links: bool, plain_when_too_deep: bool) -> PageContent:
    """``extract_page`` of a parsed page.

    Args:
        soup: The parsed page; changed in place.
        url: The page's address, for resolving relative links.
        keep_links: Keep the URL of links that sit inside a sentence.
        plain_when_too_deep: Keep the plain text of a page nested too deep to
            convert; ``False`` raises ``MarkupTooDeepError``.

    Returns:
        The page's content, as ``extract_page`` describes.

    Raises:
        MarkupTooDeepError: The page is too deep and ``plain_when_too_deep`` is off.
    """
    title = _page_title(soup)
    language = (soup.html.get("lang") if soup.html else None) or None
    root = _pick_root(soup)
    title = title or _first_heading(root)
    # Measured once the chrome is gone: a long menu beside a short article
    # isn't content the extract lost. Only the controls, which can hold a
    # page's content, count against the extract.
    _strip_chrome(root)
    plain = root.get_text("\n", strip=True)
    _strip_controls(root)
    _images_to_alt_text(root)
    _listify_link_runs(soup, root)
    markdown = soup_to_markdown(
        root, converter=_LinkConverter(url, keep_links), plain_when_too_deep=plain_when_too_deep,
    )

    if len(markdown) < _MIN_EXTRACT_SHARE * len(plain):
        logger.info(f"Page extract of {url} is near-empty ({len(markdown)} of {len(plain)} chars); keeping plain text")
        markdown = re.sub(r"\n{3,}", "\n\n", plain)
    return PageContent(text=markdown, title=title or None, language=language)


# Text a page address may serve instead of HTML (llms.txt, a raw README), kept
# as written. JSON counts only for a page added by address: there it was asked
# for, while a crawl or sitemap reaching JSON has hit an API or a feed.
_PLAIN_TEXT_TYPES = ("text/plain", "text/markdown", "text/x-markdown")
# A level-one ATX heading line. Linear on any input: the closing ``#`` run is
# stripped in Python (a lazy group between optional runs backtracked cubically).
_ATX_TITLE = re.compile(r"^#[ \t]+(.*)$", re.MULTILINE)
# A title is the text's first heading; only this much of the start is searched.
_TITLE_SCAN_CHARS = 4096


def _markdown_title(text: str) -> Optional[str]:
    """The first ``# Heading`` near the start of plain text or Markdown.

    Args:
        text: The page text.

    Returns:
        The heading without its optional closing ``#`` run, or ``None``.
    """
    match = _ATX_TITLE.search(text, 0, _TITLE_SCAN_CHARS)
    if not match:
        return None
    title = match.group(1).rstrip(" \t")
    # A closing run counts only after a space: ``# C#`` keeps its ``#``.
    unclosed = title.rstrip("#")
    if unclosed != title and (not unclosed or unclosed[-1] in " \t"):
        title = unclosed.rstrip(" \t")
    return title or None


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


_BOMS = (codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


def header_charset(content_type: Optional[str]) -> Optional[str]:
    """The charset a ``Content-Type`` header declares, when Python knows it.

    Args:
        content_type: The response's ``Content-Type``.

    Returns:
        The charset label as written, or ``None`` when there is none or it
        names no text encoding: Python also knows ``base64``, ``zlib`` or
        ``rot13`` as codecs, but bytes-to-bytes ones that no text decodes by,
        and ``idna``/``punycode`` encode host names, not pages.
    """
    match = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", content_type or "", re.IGNORECASE)
    if not match:
        return None
    try:
        codec = codecs.lookup(match.group(1))
    except LookupError:
        return None
    if not getattr(codec, "_is_text_encoding", True) or codec.name in _HOST_NAME_CODECS:
        return None
    return match.group(1)


# Codecs Python counts as text encodings that no page is written in.
_HOST_NAME_CODECS = frozenset({"idna", "punycode"})


def html_soup(html: Union[str, bytes], encoding: Optional[str] = None, parser: str = "html.parser") -> BeautifulSoup:
    """Parse a page, decoding bytes by the header's charset when it gives one.

    Args:
        html: The page.
        encoding: The ``Content-Type`` charset (``header_charset``); ``None``
            leaves BeautifulSoup to read the page's ``<meta>`` or guess. A
            byte-order mark wins over it, as in browsers.
        parser: The BeautifulSoup tree builder.

    Returns:
        The parsed page.

    Raises:
        FeatureNotFound: If ``parser`` isn't installed.
    """
    if isinstance(html, bytes) and encoding and not html.startswith(_BOMS):
        return BeautifulSoup(html, parser, from_encoding=encoding)
    return BeautifulSoup(html, parser)


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
    try:
        return body.decode(header_charset(content_type) or "utf-8", errors="replace")
    except (LookupError, UnicodeError, ValueError) as e:
        # A codec that refuses ``errors="replace"`` or fails outright: the
        # page is still read, as UTF-8.
        logger.info(f"Decoding {url} by its declared charset failed ({e}); reading it as UTF-8")
        return body.decode("utf-8", errors="replace")


def _without_nul(text: str) -> str:
    """``text`` without U+0000, which PostgreSQL text and JSONB refuse to store."""
    return text.replace("\x00", "")


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
        NUL characters are dropped from the text, title and language.
    """
    if not is_html(content_type):
        if not _is_plain_text(content_type, explicit):
            logger.info(f"Skipping {url}: {content_type} is not a web page")
            return None
        text = _without_nul(_decode_text(body, content_type, url)).strip()
        if not text:
            logger.info(f"Skipping {url}: no text")
            return None
        metadata = {"source": url}
        # JSON has no headings to title it by.
        title = _markdown_title(text) if _media_type(content_type) in _PLAIN_TEXT_TYPES else None
        if title:
            metadata["title"] = title
        metadata["file_path"] = url_to_virtual_path(url, include_host)
        return Document(text, extra_info=metadata)
    page = extract_page(body, url, keep_links=keep_links, encoding=header_charset(content_type))
    text = _without_nul(page.text)
    if not text.strip():
        logger.info(f"Skipping {url}: no text")
        return None
    metadata = {"source": url}
    title = _without_nul(page.title or "").strip()
    if title:
        metadata["title"] = title
    language = _without_nul(page.language or "").strip()
    if language:
        metadata["language"] = language
    # The worker keys the file tree by file_path; the chunks view filters by it.
    metadata["file_path"] = url_to_virtual_path(url, include_host)
    return Document(text, extra_info=metadata)
