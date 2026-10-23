import logging
from typing import Callable, List, Optional, Union
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from docsgpt.parser.remote.base import BaseRemote, dedupe_virtual_paths, normalize_page_url, url_to_virtual_path
from docsgpt.parser.remote.page_content import FetchBudget, fetch_page, is_html, page_document
from docsgpt.parser.schema.base import Document
from docsgpt.core.url_validation import validate_url, SSRFError


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

        # Keyed by normalize_page_url, so fragment and query-order variants of
        # one page are fetched once.
        visited_urls = set()
        start = urlparse(url)
        site = (start.scheme, start.hostname)
        urls_to_visit = [url]
        loaded_content = []

        while urls_to_visit:
            # Checked before each fetch, so failed and non-page fetches count
            # toward the limit too instead of letting the crawl run past it.
            if self.limit is not None and len(visited_urls) >= self.limit:
                self.limit_reached = any(normalize_page_url(u) not in visited_urls for u in urls_to_visit)
                break
            current_url = urls_to_visit.pop(0)
            page_key = normalize_page_url(current_url)
            if page_key in visited_urls:
                continue
            if self.budget is not None and not self.budget.take():
                self.limit_reached = True
                break
            visited_urls.add(page_key)

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
                loaded_content.append(document)
                if not is_html(content_type):
                    # Plain text or Markdown: kept, but its "links" are text.
                    continue
                soup = BeautifulSoup(body, "html.parser")
            except Exception as e:
                logging.error(f"Error processing URL {current_url}: {e}", exc_info=True)
                continue

            # Parse the HTML content to extract all links. A malformed href
            # (``http://[bad``) makes urljoin or the key parse raise; skip it
            # rather than abort the crawl.
            all_links = []
            for a in soup.find_all('a', href=True):
                try:
                    link = urljoin(current_url, a['href'])
                    link_key = normalize_page_url(link)
                    parsed_link = urlparse(link)
                except ValueError:
                    continue
                if self.accept is not None:
                    on_site = self.accept(link)
                else:
                    # Compare the host itself: a substring match also follows
                    # share links and lookalike hosts that contain the site URL.
                    on_site = (parsed_link.scheme, parsed_link.hostname) == site
                if on_site and link_key not in visited_urls:
                    all_links.append(link)

            # Add new links to the list of URLs to visit if they haven't been visited yet
            urls_to_visit.extend(all_links)
            urls_to_visit = list(set(urls_to_visit))

        return dedupe_virtual_paths(loaded_content)

    def _url_to_virtual_path(self, url):
        """Convert a URL to a virtual ``.md`` path; see ``url_to_virtual_path``."""
        return url_to_virtual_path(url)
