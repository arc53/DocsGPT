"""A crawl of one site's links, for the Website loader's ``links`` discovery."""

import logging
from collections import deque
from typing import Callable, List, Optional, Union
from urllib.parse import urldefrag, urljoin

from docsgpt.parser.remote.base import BaseRemote, dedupe_virtual_paths
from docsgpt.parser.remote.page_content import (
    FetchBudget,
    fetch_page,
    final_url,
    has_userinfo,
    header_charset,
    html_soup,
    is_html,
    link_base,
    note_requested_url,
    page_document,
    page_key,
    within_url_limits,
)
from docsgpt.parser.schema.base import Document
from docsgpt.core.url_validation import validate_url, SSRFError

# Links a crawl holds waiting, per page of its limit (or in all, with no
# limit). A crawl of N pages fetches at most N of them, so more is dead weight.
_QUEUE_PER_PAGE = 10
_MAX_QUEUE = 10_000


class CrawlerLoader(BaseRemote):
    """Crawls breadth first from a start page, following the links a scope accepts."""

    def __init__(
        self,
        accept: Callable[[str], bool],
        limit: Optional[int] = None,
        keep_links: bool = False,
        budget: Optional[FetchBudget] = None,
    ):
        """
        Args:
            accept: Which links to follow and pages to keep (``SiteScope.accepts``).
            limit: Most pages to fetch (``None`` for no cap).
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
            when the scope accepts that address too; ``requested_urls`` holds
            the links it was reached by (``note_requested_url``), a later one
            that redirects to it included.
        """
        url = inputs
        if isinstance(url, list) and url:
            url = url[0]

        # Validate URL to prevent SSRF attacks
        try:
            url = validate_url(url)
        except (SSRFError, ValueError) as e:
            logging.error(f"URL validation failed: {e}")
            return []
        if not within_url_limits(url):
            logging.error(f"Not crawling from an address too long or too deep to fetch: {url[:200]}")
            return []

        # Breadth-first in link order, so a capped crawl takes the same pages
        # every time. Keyed by page_key, so fragment, query-order, slash,
        # www. and scheme variants of one page are fetched once; ``seen``
        # holds every page queued or fetched, ``done`` every page fetched
        # (a redirect's target included).
        seed_key = page_key(url)
        seen = {seed_key}
        done = set()
        queue = deque([url])
        # Links waiting beyond this are dropped: the crawl can't reach them.
        max_queue = _QUEUE_PER_PAGE * self.limit if self.limit is not None else _MAX_QUEUE
        loaded_content = []
        # The document of each page kept, by page_key.
        by_key = {}
        # The start page is fetched for its links even when the scope leaves
        # it out (starting at / with Stay under /docs, or a skipped start
        # page); only its content is dropped.
        keep_seed = self.accept(url)
        # Fetches charged to the limit: every one but a start page that isn't
        # kept (the fetch budget is still charged for it).
        charged = 0

        while queue:
            # Checked before each fetch, so failed and non-page fetches count
            # toward the limit too instead of letting the crawl run past it.
            if self.limit is not None and charged >= self.limit:
                # Left over only if a queued page wasn't reached by a redirect.
                self.limit_reached = any(page_key(link) not in done for link in queue)
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
                if page_url != current_url:
                    # Redirected: the page is where it landed, which must be
                    # new and in scope like any link. Checked even when the
                    # key stays (``x.io/a`` to ``www.x.io/a``): a section
                    # rule names its host exactly.
                    final_key = page_key(page_url)
                    if final_key != current_key:
                        if final_key in done:
                            if final_key in by_key:
                                # A page already loaded: this link is another way to it.
                                note_requested_url(by_key[final_key], current_url)
                            continue
                        done.add(final_key)
                        seen.add(final_key)
                    keep = self._on_site(page_url)
                    if not keep and not is_seed:
                        logging.info(f"Dropping {current_url}: it redirects out of scope to {page_url}")
                        continue
                    if keep and is_seed and not keep_seed:
                        # A start page outside the scope that lands inside it
                        # is kept, so it counts toward the limit after all.
                        charged += 1
                body = response.content
                content_type = response.headers.get("Content-Type")
                html = is_html(content_type)
                try:
                    document = page_document(body, content_type, page_url, keep_links=self.keep_links)
                except Exception as e:
                    if not html:
                        raise
                    # Its links are still read below: a page the extractor
                    # can't handle mustn't cut off the pages it leads to.
                    logging.error(f"Error extracting {current_url}; following its links only: {e}", exc_info=True)
                    document = None
                if document is not None and keep:
                    # The worker matches the tree entry by any address that led to it.
                    note_requested_url(document, current_url)
                    by_key[page_key(page_url)] = document
                    loaded_content.append(document)
                if not html:
                    # Not a page (a PDF or image the site links to), or plain
                    # text or Markdown whose "links" are text: none to follow.
                    continue
                # An HTML page with no text of its own (only a menu, header or
                # footer) is no document, but its links are the way on.
                # The header's charset, as for the page text: a link's path
                # read in the wrong one is a different address.
                soup = html_soup(body, header_charset(content_type))
            except Exception as e:
                logging.error(f"Error processing URL {current_url}: {e}", exc_info=True)
                continue

            # Queue the page's links in document order, resolved as a browser
            # does: against the page's ``<base href>``, the href stripped of
            # surrounding whitespace, and without its fragment (a spot on the
            # page, never part of the stored address). A malformed href
            # (``http://[bad``) makes urljoin or the key parse raise; skip it
            # rather than abort the crawl.
            base = link_base(soup, page_url)
            for a in soup.find_all('a', href=True):
                if len(queue) >= max_queue:
                    break
                try:
                    link = urldefrag(urljoin(base, str(a['href']).strip()))[0]
                    link_key = page_key(link)
                except ValueError:
                    continue
                if has_userinfo(link):
                    # ``user:password@``: never fetched, nor stored as a page.
                    continue
                if link_key in seen:
                    continue
                if self._on_site(link):
                    seen.add(link_key)
                    queue.append(link)

        return dedupe_virtual_paths(loaded_content)

    def _on_site(self, url: str) -> bool:
        """Whether the crawl may take ``url``: ``accept`` says so and it is within ``within_url_limits``."""
        return within_url_limits(url) and self.accept(url)
