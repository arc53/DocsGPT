import logging
from collections import deque
from typing import Callable, List, Optional, Union
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from docsgpt.parser.remote.base import BaseRemote, dedupe_virtual_paths, url_to_virtual_path
from docsgpt.parser.remote.page_content import FetchBudget, fetch_page, is_html, page_document, page_key
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
            One document per page that loaded, at most ``limit`` fetches.
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
        # holds every page queued or fetched.
        start = urlparse(url)
        site = (start.scheme, start.hostname)
        seed_key = page_key(url)
        seen = {seed_key}
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
            if self.budget is not None and not self.budget.take():
                self.limit_reached = True
                break
            is_seed = current_key == seed_key
            if keep_seed or not is_seed:
                charged += 1

            try:
                # Capped at the page size gate: the links come from the same
                # bytes the document does.
                response = fetch_page(current_url, timeout=30)
                response.raise_for_status()
                body = response.content
                content_type = response.headers.get("Content-Type")
                document = page_document(body, content_type, current_url, keep_links=self.keep_links)
                if document is None:
                    # Not a page (a PDF or image the site links to): no text
                    # to keep and no links to follow.
                    continue
                if keep_seed or not is_seed:
                    loaded_content.append(document)
                if not is_html(content_type):
                    # Plain text or Markdown: kept, but its "links" are text.
                    continue
                soup = BeautifulSoup(body, "html.parser")
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
                    link = urljoin(current_url, a['href'])
                    link_key = page_key(link)
                    parsed_link = urlparse(link)
                except ValueError:
                    continue
                if link_key in seen:
                    continue
                if self.accept is not None:
                    on_site = self.accept(link)
                else:
                    # Compare the host itself: a substring match also follows
                    # share links and lookalike hosts that contain the site URL.
                    on_site = (parsed_link.scheme, parsed_link.hostname) == site
                if on_site:
                    seen.add(link_key)
                    queue.append(link)

        return dedupe_virtual_paths(loaded_content)

    def _url_to_virtual_path(self, url):
        """Convert a URL to a virtual ``.md`` path; see ``url_to_virtual_path``."""
        return url_to_virtual_path(url)
