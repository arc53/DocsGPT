import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from docsgpt.parser.remote.base import BaseRemote, dedupe_virtual_paths, normalize_page_url, url_to_virtual_path
from docsgpt.parser.remote.page_content import page_document
from docsgpt.core.url_validation import validate_url, SSRFError
from docsgpt.security.safe_url import pinned_request


class CrawlerLoader(BaseRemote):
    def __init__(self, limit=10):
        self.limit = limit  # Set the limit for the number of pages to scrape

    def load_data(self, inputs):
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
                break
            current_url = urls_to_visit.pop(0)
            page_key = normalize_page_url(current_url)
            if page_key in visited_urls:
                continue
            visited_urls.add(page_key)

            try:
                response = pinned_request("GET", current_url, timeout=30)
                response.raise_for_status()
                document = page_document(
                    response.content, response.headers.get("Content-Type"), current_url,
                )
                if document is None:
                    # Not a page (a PDF or image the site links to): no text
                    # to keep and no links to follow.
                    continue
                loaded_content.append(document)
                soup = BeautifulSoup(response.content, "html.parser")
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
