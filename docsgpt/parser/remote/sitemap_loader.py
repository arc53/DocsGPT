import codecs
import io
import logging
import re
import zlib
from typing import Callable, List, Optional, Set, Union

import defusedxml.ElementTree as ET
import requests

from docsgpt.parser.remote.base import (
    BaseRemote,
    dedupe_virtual_paths,
    spans_multiple_hosts,
)
from docsgpt.parser.remote.page_content import FetchBudget, fetch_page, final_url, page_document, page_key
from docsgpt.parser.schema.base import Document
from docsgpt.core.url_validation import validate_url, SSRFError
from docsgpt.security.safe_url import UnsafeUserUrlError

logger = logging.getLogger(__name__)

# How many levels of nested sitemap indexes to follow below the one the user
# gave. Real sites use one or two; past this it is a loop or a trap.
MAX_SITEMAP_DEPTH = 5

# How many sitemap files one walk fetches in all, the given ones included.
# Large sites split by section or by date into a few dozen; an index listing
# thousands of children is a crawl trap, and each child is a fetch.
MAX_SITEMAPS_PER_WALK = 50

# The sitemaps protocol caps an uncompressed sitemap at 50 MB; a gzip that
# inflates past it is refused rather than decompressed into memory. A
# download past it (after Content-Encoding is undone) is refused too.
MAX_SITEMAP_BYTES = 50 * 1024 * 1024
_GZIP_MAGIC = b"\x1f\x8b"
# How much of a response to look at for a root tag, when its type doesn't say.
_SNIFF_BYTES = 64 * 1024


def _local_name(tag: object) -> str:
    """An XML tag without its namespace (``{ns}loc`` and ``loc`` are ``loc``)."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _gunzip(data: bytes, url: str) -> Optional[bytes]:
    """Decompress a gzip sitemap, refusing one that inflates past the cap.

    Args:
        data: The gzip bytes.
        url: The sitemap's URL, for the log.

    Returns:
        The XML bytes, or ``None`` when the file is corrupt or too large.
    """
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        content = inflater.decompress(data, MAX_SITEMAP_BYTES + 1)
    except zlib.error as e:
        logger.warning(f"Skipping sitemap {url}: not valid gzip ({e})")
        return None
    if len(content) > MAX_SITEMAP_BYTES or inflater.unconsumed_tail:
        logger.warning(f"Skipping sitemap {url}: inflates past {MAX_SITEMAP_BYTES} bytes")
        return None
    return content


# An XML declaration at the start of a document, and the encoding it names.
_XML_DECLARATION = re.compile(rb"\s*<\?xml\s[^>]{0,512}?\?>")
_DECLARED_ENCODING = re.compile(rb"""encoding\s*=\s*["']([A-Za-z0-9._:-]{1,64})["']""")
_UTF8_BOM = b"\xef\xbb\xbf"


def _as_utf8(content: bytes, url: str = "") -> bytes:
    """Sitemap bytes in a form expat reads, whatever encoding they declare.

    expat reads UTF-8, UTF-16 and Latin-1 itself, but refuses multi-byte
    codecs (GBK, Shift_JIS, EUC-KR, Big5) and unknown labels, which failed
    the whole ingest. A document declaring anything but UTF-8 is decoded
    here with the declared codec (UTF-8 when Python doesn't know the label;
    bad bytes become U+FFFD) and handed on as UTF-8 without its declaration.

    Args:
        content: The raw sitemap bytes.
        url: The sitemap's URL, for the log.

    Returns:
        The bytes as they were when they are UTF-8 (or a BOM or no ASCII
        declaration says so), else the document re-encoded as UTF-8.
    """
    if content.startswith(_UTF8_BOM):
        return content
    declaration = _XML_DECLARATION.match(content)
    encoding = _DECLARED_ENCODING.search(declaration.group(0)) if declaration else None
    if encoding is None:
        return content
    label = encoding.group(1).decode("ascii")
    try:
        codec = codecs.lookup(label).name
    except LookupError:
        logger.warning(f"Sitemap {url} declares an unknown encoding {label!r}; reading it as UTF-8")
        codec = None
    if codec == "utf-8":
        return content
    # A declaration readable as ASCII bytes isn't UTF-16 or UTF-32, whatever it says.
    if codec is None or codec.startswith(("utf-16", "utf-32")):
        codec = "utf-8"
    return content[declaration.end():].decode(codec, errors="replace").encode("utf-8")


def _read_entries(
    content: bytes,
    on_page: Callable[[str], None],
    on_child: Callable[[str], None],
    done: Callable[[], bool],
) -> bool:
    """Read a sitemap's ``<url>`` and ``<sitemap>`` entries incrementally.

    Every element is dropped from the tree once it is read, whatever its tag,
    so a 50 MB sitemap (or a small gzip of millions of junk elements) never
    becomes a large tree. Tags match by local name, whatever the namespace
    and however it is quoted. The defusedxml parser keeps entities and
    external references out. XML that stops parsing keeps the entries read
    before the error.

    Args:
        content: Raw sitemap XML, in its declared encoding (see ``_as_utf8``).
        on_page: Called with each ``<url>``'s first ``<loc>``.
        on_child: Called with each ``<sitemap>``'s first ``<loc>``.
        done: Checked after each entry; True stops the reading.

    Returns:
        False when ``done`` stopped the reading, True otherwise.
    """
    # [element, the first <loc> read inside it] for each open element.
    open_elements: List[list] = []
    try:
        for event, element in ET.iterparse(io.BytesIO(_as_utf8(content)), events=("start", "end")):
            if event == "start":
                open_elements.append([element, ""])
                continue
            _, address = open_elements.pop()
            parent = open_elements[-1] if open_elements else None
            name = _local_name(element.tag)
            if name == "loc":
                if parent is not None and not parent[1] and _local_name(parent[0].tag) in ("url", "sitemap"):
                    parent[1] = (element.text or "").strip()
            elif name == "url" and address:
                on_page(address)
            elif name == "sitemap" and address:
                on_child(address)
            # Earlier siblings are gone, so this is the parent's only child.
            element.clear()
            if parent is not None:
                parent[0].remove(element)
            if name in ("url", "sitemap") and done():
                return False
    except (ET.ParseError, ValueError, LookupError) as e:
        # ValueError covers defusedxml's refusals and an encoding expat
        # still won't take: one bad sitemap never fails the ingest.
        logger.warning(f"Stopped reading a sitemap that could not be parsed: {e}")
    return True


class SitemapLoader(BaseRemote):
    def __init__(
        self,
        limit: Optional[int] = 20,
        accept: Optional[Callable[[str], bool]] = None,
        keep_links: bool = False,
        budget: Optional[FetchBudget] = None,
    ):
        """
        Args:
            limit: Most pages to load; the sitemap walk stops collecting once
                it has this many (``None`` for no cap).
            accept: Which page URLs count. Applied while walking, so the limit
                takes the sitemap's own order after exclusions.
            keep_links: Keep the URL of links inside sentences in page text.
            budget: Fetches the whole load may still make, sitemaps and pages
                alike; ``None`` for no cap.
        """
        self.limit = limit
        self.accept = accept
        self.keep_links = keep_links
        self.budget = budget
        # Whether the last walk found more pages than the limit took.
        self.limit_reached = False
        # page_key of every page URL the current walk collected, so
        # duplicates and variants (``/a``, ``/a/``, ``/a#x``) count once.
        self._collected: Set[str] = set()

    def load_data(self, inputs: Union[str, List[str]]) -> List[Document]:
        """Walk a sitemap and load the pages it lists.

        Args:
            inputs: The sitemap URL (or a list whose first item is). A URL
                that isn't a sitemap is loaded as a page.

        Returns:
            One document per page that loaded, at most ``limit``.
        """
        sitemap_url= inputs
        # Check if the input is a list and if it is, use the first element
        if isinstance(sitemap_url, list) and sitemap_url:
            sitemap_url = sitemap_url[0]

        # Validate URL to prevent SSRF attacks
        try:
            sitemap_url = validate_url(sitemap_url)
        except SSRFError as e:
            logger.error(f"URL validation failed: {e}")
            return []

        urls = self._extract_urls(sitemap_url)
        if not urls:
            logger.warning(f"No URLs found in the sitemap: {sitemap_url}")
            return []
        return self.load_pages(urls)

    def collect_urls(self, sitemap_urls: List[str]) -> List[str]:
        """Walk several sitemaps in order against one shared page budget.

        A URL that turns out not to be a sitemap is skipped rather than taken
        as a page (a soft 404 at ``/sitemap.xml`` is an HTML shell).

        Args:
            sitemap_urls: Sitemap or sitemap-index URLs.

        Returns:
            Accepted page URLs, in sitemap order, at most ``limit`` of them,
            each page once (by ``page_key``, across all the sitemaps).
            ``limit_reached`` says whether the sitemaps list more.
        """
        visited: Set[str] = set()
        self._collected = set()
        urls: List[str] = []
        # One URL past the limit tells "exactly the limit" from "more left".
        wanted = None if self.limit is None else self.limit + 1
        for sitemap_url in sitemap_urls:
            remaining = None if wanted is None else wanted - len(urls)
            if remaining is not None and remaining <= 0:
                break
            found = self._walk(sitemap_url, visited, 0, remaining)
            if found:
                urls.extend(found)
        self.limit_reached = self.limit is not None and len(urls) > self.limit
        return urls if self.limit is None else urls[: self.limit]

    def load_pages(self, urls: List[str]) -> List[Document]:
        """Fetch page URLs (already collected from a sitemap) into documents.

        Args:
            urls: Page URLs in the order to load them.

        Returns:
            One document per page that loaded, at most ``limit``.
        """
        include_host = spans_multiple_hosts(urls)
        documents = []
        processed_urls = 0  # Counter for processed URLs
        loaded = set()
        for url in urls:
            if self.limit is not None and processed_urls >= self.limit:
                break  # Stop processing if the limit is reached
            try:
                key = page_key(url)
            except ValueError:
                key = url
            if key in loaded:
                continue
            loaded.add(key)

            try:
                url = validate_url(url)
            except SSRFError as e:
                logger.error(f"URL validation failed for sitemap entry {url}: {e}")
                continue
            if self.budget is not None and not self.budget.take():
                logger.warning(f"Fetch budget spent; not fetching {url}")
                self.limit_reached = True
                break
            try:
                response = fetch_page(url, timeout=30, budget=self.budget)
                response.raise_for_status()
                page_url = final_url(response, url)
                if page_url != url:
                    # Redirected: stored where it landed, which must be a new
                    # page the scope takes; otherwise it is dropped like a
                    # failed fetch.
                    landed = page_key(page_url)
                    if landed != key and landed in loaded:
                        continue
                    if self.accept is not None and not self.accept(page_url):
                        logger.info(f"Dropping {url}: it redirects out of scope to {page_url}")
                        continue
                    loaded.add(landed)
                # A shared extractor, so sitemap pages get a title like the
                # others do (their citations showed a wall of chunk text).
                document = page_document(
                    response.content,
                    response.headers.get("Content-Type"),
                    page_url,
                    include_host=include_host,
                    keep_links=self.keep_links,
                )
                if document is not None:
                    documents.append(document)
                processed_urls += 1  # Increment the counter after processing each URL
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}", exc_info=True)
                continue

        return dedupe_virtual_paths(documents)

    def _extract_urls(
        self,
        sitemap_url: str,
        visited: Optional[Set[str]] = None,
        depth: int = 0,
        budget: Optional[int] = None,
    ) -> List[str]:
        """Fetch a sitemap (or page) URL and return the page URLs it lists.

        Args:
            sitemap_url: The sitemap or page URL to fetch.
            visited: Sitemap URLs already fetched in this walk (see ``_walk``).
            depth: How many sitemap indexes deep this URL is.
            budget: How many more URLs the walk may collect.

        Returns:
            At most ``budget`` page URLs, or ``[sitemap_url]`` when it is not
            a sitemap (the legacy sitemap loader then loads it as a page).
        """
        found = self._walk(sitemap_url, visited, depth, budget)
        return [sitemap_url] if found is None else found

    def _walk(
        self,
        sitemap_url: str,
        visited: Optional[Set[str]] = None,
        depth: int = 0,
        budget: Optional[int] = None,
    ) -> Optional[List[str]]:
        """Fetch a sitemap and return the page URLs it and its children list.

        Each sitemap is fetched at most once per walk, nested sitemap indexes
        are followed at most ``MAX_SITEMAP_DEPTH`` levels deep, and a walk
        fetches at most ``MAX_SITEMAPS_PER_WALK`` sitemaps, so a sitemap that
        lists itself (or a ring, or thousands of children) cannot run away.

        Args:
            sitemap_url: The sitemap URL to fetch.
            visited: Sitemap URLs already fetched in this walk; shared with
                the nested calls. ``None`` starts a new walk.
            depth: How many sitemap indexes deep this URL is.
            budget: How many more URLs the walk may collect. ``None`` starts
                from ``limit`` (itself ``None`` for no cap).

        Returns:
            At most ``budget`` page URLs; ``None`` when the URL answered but
            is not a sitemap.
        """
        budget = self.limit if budget is None else budget
        if budget is not None and budget <= 0:
            return []
        if visited is None:
            visited = set()
            self._collected = set()
        key = sitemap_url.strip()
        if key in visited:
            logger.warning(f"Skipping already-visited sitemap: {sitemap_url}")
            return []
        if depth > MAX_SITEMAP_DEPTH:
            logger.warning(
                f"Not following sitemap {sitemap_url}: nesting depth exceeds {MAX_SITEMAP_DEPTH}"
            )
            return []
        if len(visited) >= MAX_SITEMAPS_PER_WALK:
            logger.warning(f"Not following sitemap {sitemap_url}: the walk read {MAX_SITEMAPS_PER_WALK} sitemaps")
            return []
        if self.budget is not None and not self.budget.take():
            logger.warning(f"Fetch budget spent; not fetching sitemap {sitemap_url}")
            return []
        visited.add(key)

        try:
            response = fetch_page(sitemap_url, MAX_SITEMAP_BYTES, timeout=30, truncate=False, budget=self.budget)
            response.raise_for_status()
        except UnsafeUserUrlError as e:
            logger.error(f"URL validation failed for sitemap: {sitemap_url}. Error: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch sitemap: {sitemap_url}. Error: {e}")
            return []

        # A .xml.gz sitemap arrives as gzip bytes (Content-Encoding gzip is
        # undone by requests; a gzip *file* is not).
        if isinstance(response.content, bytes) and response.content[:2] == _GZIP_MAGIC:
            content = _gunzip(response.content, sitemap_url)
            if content is None:
                return []
            return self._parse_sitemap(content, visited, depth, budget)

        # Determine if this is a sitemap or a URL
        if self._is_sitemap(response):
            # It's a sitemap, so parse it and extract URLs
            return self._parse_sitemap(response.content, visited, depth, budget)
        return None

    def _is_sitemap(self, response: requests.Response) -> bool:
        """Whether a fetched response is sitemap XML (by type, extension or a root tag near the start)."""
        content_type = response.headers.get('Content-Type', '')
        if 'xml' in content_type or response.url.endswith('.xml'):
            return True
        # Sniff the head of the bytes: decoding a whole large body as text
        # guesses its charset over every byte.
        content = response.content
        head = content[:_SNIFF_BYTES] if isinstance(content, bytes) else (response.text or "").encode()
        return b"<sitemapindex" in head or b"<urlset" in head

    def _parse_sitemap(
        self,
        sitemap_content: bytes,
        visited: Optional[Set[str]] = None,
        depth: int = 0,
        budget: Optional[int] = None,
    ) -> List[str]:
        """Return the page URLs in a sitemap, following nested sitemap indexes.

        The URL budget is shared by the whole walk: once it is spent, no more
        page URLs are collected (the file isn't read further) and no more
        child sitemaps are fetched. XML that stops parsing keeps the entries
        read before the error rather than failing the whole ingest. A child
        entry that turns out not to be a sitemap is dropped: only ``<url>``
        entries are pages, and only after ``accept``. A page counts once per
        walk (by ``page_key``).

        Args:
            sitemap_content: Raw sitemap XML, in its declared encoding.
            visited: Sitemap URLs already fetched in this walk.
            depth: How many sitemap indexes deep this sitemap is.
            budget: How many more URLs the walk may collect. ``None`` starts
                from ``limit`` (itself ``None`` for no cap).

        Returns:
            At most ``budget`` page URLs from this sitemap and the children it
            was allowed to follow.
        """
        budget = self.limit if budget is None else budget
        if visited is None:
            visited = set()
            self._collected = set()
        urls: List[str] = []
        children: List[str] = []

        def remaining() -> Optional[int]:
            return None if budget is None else budget - len(urls)

        def take_page(url: str) -> None:
            # Scope first: a sitemap can list a million pages of other hosts.
            if self.accept is not None and not self.accept(url):
                return
            try:
                key = page_key(url)
            except ValueError:
                return
            if key in self._collected:
                return
            self._collected.add(key)
            urls.append(url)

        def take_child(url: str) -> None:
            if len(children) < MAX_SITEMAPS_PER_WALK:
                children.append(url)

        # The tree is gone once this returns, so it isn't held while the
        # child sitemaps are walked.
        if not _read_entries(sitemap_content, take_page, take_child, lambda: remaining() == 0):
            return urls

        # Check for nested sitemaps
        for nested_sitemap_url in children:
            if remaining() == 0:
                break
            urls.extend(self._walk(nested_sitemap_url, visited, depth + 1, remaining()) or [])

        return urls
