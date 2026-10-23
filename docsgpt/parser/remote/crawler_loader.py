import logging
from collections import deque
from typing import Callable, List, Optional, Union
from urllib.parse import urljoin, urlsplit

from docsgpt.parser.remote.base import BaseRemote, dedupe_virtual_paths, url_to_virtual_path
from docsgpt.parser.remote.page_content import (
    FetchBudget,
    fetch_page,
    final_url,
    header_charset,
    host_with_port,
    html_soup,
    is_html,
    page_document,
    page_key,
)
from docsgpt.parser.schema.base import Document
from docsgpt.core.url_validation import validate_url, SSRFError

# Links a crawl holds waiting, per page of its limit (or in all, with no
# limit). A crawl of N pages fetches at most N of them, so more is dead weight.
_QUEUE_PER_PAGE = 10
_MAX_QUEUE = 10_000


class CrawlerLoader(BaseRemote):
    def __init__(
        self,
        limit: Optional[int] = 10,
        accept: Optional[Callable[[str], bool]] = None,
        keep_links: bool = False,
        budget: Optional[FetchBudget] = None,
    ):
        """
        Args:
            limit: Most pages to fetch (``None`` for no cap).
            accept: Which links to follow. Default: the start page's scheme
                and host.
            keep_links: Keep the URL of links inside sentences in page text.
            budget: Fetches the whole load may still make; ``None`` for no cap.
        """
        self.limit = limit
        self.accept = accept
        self.keep_links = keep_links
        self.budget = budget
        # Whether the last crawl stopped at the limit with pages left to visit.
        self.limit_reached = False

    def load_data(self, inputs: Union[str, List[str]]) -> List[Document]:
        """Crawl from a start page, following links the scope accepts.

        Args:
            inputs: The start URL (or a list whose first item is).

        Returns:
            One document per page that loaded, at most ``limit`` fetches. A
            page that redirects is stored under its final address, and only
            when the scope accepts that address too.
        """
        url = inputs
        if isinstance(url, list) and url:
            url = url[0]

        # Validate URL to prevent SSRF attacks
        try:
            url = validate_url(url)
        except SSRFError as e:
            logging.error(f"URL validation failed: {e}")
            return []

        # Breadth-first in link order, so a capped crawl takes the same pages
        # every time. Keyed by page_key, so fragment, query-order, slash,
        # www. and scheme variants of one page are fetched once; ``seen``
        # holds every page queued or fetched, ``done`` every page fetched
        # (a redirect's target included).
        site_host = _site_of(url)
        seed_key = page_key(url)
        seen = {seed_key}
        done = set()
        queue = deque([url])
        # Links waiting beyond this are dropped: the crawl can't reach them.
        max_queue = _QUEUE_PER_PAGE * self.limit if self.limit is not None else _MAX_QUEUE
        loaded_content = []
        # The start page is fetched for its links even when the scope leaves
        # it out (starting at / with Stay under /docs, or a skipped start
        # page); only its content is dropped.
        keep_seed = self.accept is None or self.accept(url)
        # Fetches charged to the limit: every one but a start page that isn't
        # kept (the fetch budget is still charged for it).
        charged = 0

        while queue:
            # Checked before each fetch, so failed and non-page fetches count
            # toward the limit too instead of letting the crawl run past it.
            if self.limit is not None and charged >= self.limit:
                self.limit_reached = True
                break
            current_url = queue.popleft()
            current_key = page_key(current_url)
            if current_key in done:
                # An earlier page redirected here.
                continue
            done.add(current_key)
            if self.budget is not None and not self.budget.take():
                self.limit_reached = True
                break
            is_seed = current_key == seed_key
            if keep_seed or not is_seed:
                charged += 1

            try:
                # Capped at the page size gate: the links come from the same
                # bytes the document does.
                response = fetch_page(current_url, timeout=30, budget=self.budget)
                response.raise_for_status()
                page_url = final_url(response, current_url)
                keep = keep_seed if is_seed else True
                final_key = page_key(page_url)
                if final_key != current_key:
                    # Redirected: the page is where it landed, which must be
                    # new and in scope like any link.
                    if final_key in done:
                        continue
                    done.add(final_key)
                    seen.add(final_key)
                    keep = self._on_site(page_url, site_host)
                    if not keep and not is_seed:
                        logging.info(f"Dropping {current_url}: it redirects out of scope to {page_url}")
                        continue
                body = response.content
                content_type = response.headers.get("Content-Type")
                document = page_document(body, content_type, page_url, keep_links=self.keep_links)
                if document is None:
                    # Not a page (a PDF or image the site links to): no text
                    # to keep and no links to follow.
                    continue
                if keep:
                    loaded_content.append(document)
                if not is_html(content_type):
                    # Plain text or Markdown: kept, but its "links" are text.
                    continue
                # The header's charset, as for the page text: a link's path
                # read in the wrong one is a different address.
                soup = html_soup(body, header_charset(content_type))
            except Exception as e:
                logging.error(f"Error processing URL {current_url}: {e}", exc_info=True)
                continue

            # Queue the page's links in document order. A malformed href
            # (``http://[bad``) makes urljoin or the key parse raise; skip it
            # rather than abort the crawl.
            for a in soup.find_all('a', href=True):
                if len(queue) >= max_queue:
                    break
                try:
                    link = urljoin(page_url, a['href'])
                    link_key = page_key(link)
                except ValueError:
                    continue
                if link_key in seen:
                    continue
                if self._on_site(link, site_host):
                    seen.add(link_key)
                    queue.append(link)

        return dedupe_virtual_paths(loaded_content)

    def _on_site(self, url: str, site_host: Optional[str]) -> bool:
        """Whether the crawl may take ``url``: ``accept``, else the start page's host and port.

        Args:
            url: A link or a redirect's target.
            site_host: The start page's ``host[:port]`` (``_site_of``), for a
                crawl without ``accept``.

        Returns:
            True when the page is in scope.
        """
        if self.accept is not None:
            return self.accept(url)
        try:
            parsed = urlsplit(url)
            # Compare the host itself: a substring match also follows share
            # links and lookalike hosts that contain the site URL. Another
            # port is another server.
            return parsed.scheme in ("http", "https") and _site_of(url) == site_host
        except ValueError:
            return False

    def _url_to_virtual_path(self, url):
        """Convert a URL to a virtual ``.md`` path; see ``url_to_virtual_path``."""
        return url_to_virtual_path(url)


def _site_of(url: str) -> Optional[str]:
    """The ``host[:port]`` a crawl without ``accept`` stays on (a port only when it isn't the scheme's own).

    Args:
        url: An address.

    Returns:
        The host, with a port of its own; ``None`` for an address without a host.

    Raises:
        ValueError: If the address or its port cannot be parsed.
    """
    parts = urlsplit(url)
    return host_with_port(parts, parts.hostname) if parts.hostname else None
