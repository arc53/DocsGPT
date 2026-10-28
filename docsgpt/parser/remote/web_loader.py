"""Page entries: each address fetched as one page."""

import logging
from typing import List, Optional, Union

from docsgpt.core.url_validation import SSRFError, validate_url
from docsgpt.parser.remote.base import (
    BaseRemote,
    dedupe_virtual_paths,
    spans_multiple_hosts,
)
from docsgpt.parser.remote.page_content import (
    FetchBudget,
    fetch_page,
    final_url,
    merge_requested_urls,
    note_requested_url,
    page_document,
    page_key,
    within_url_limits,
)
from docsgpt.parser.schema.base import Document


class WebLoader(BaseRemote):
    """Fetches each address it is given as one page."""

    def __init__(self, keep_links: bool = False, budget: Optional[FetchBudget] = None):
        """
        Args:
            keep_links: Keep the URL of links inside sentences in page text.
            budget: Fetches the whole load may still make; ``None`` for no cap.
        """
        self.keep_links = keep_links
        self.budget = budget

    def load_data(self, inputs: Union[str, List[str]]) -> List[Document]:
        """Fetch each address as one page.

        Args:
            inputs: A URL or a list of them.

        Returns:
            One document per page that loaded, its ``source`` the address a
            redirect led to and ``requested_urls`` the other addresses asked
            for that led to it (``note_requested_url``); addresses that land
            on one page are one document. A blocked address, a failed fetch
            or a response with no text is skipped.
        """
        urls = inputs
        if isinstance(urls, str):
            urls = [urls]
        valid_urls = []
        for url in urls:
            if not within_url_limits(url):
                # A stored entry from before the write limits: a folder per segment.
                logging.warning(f"Skipping an address too long or too deep to fetch: {url[:200]}")
                continue
            try:
                valid_urls.append(validate_url(url))
            except (SSRFError, ValueError) as e:
                # ValueError: a host the idna codec refuses; the other pages still load.
                logging.warning(
                    f"Skipping URL due to SSRF validation failure: {url} - {e}"
                )
        include_host = spans_multiple_hosts(valid_urls)
        documents = []
        # The document of each page, by page_key: addresses that redirect to
        # one page are one document listing them all.
        by_key = {}
        for url in valid_urls:
            if self.budget is not None and not self.budget.take():
                logging.warning(f"Fetch budget spent; not fetching {url}")
                break
            try:
                response = fetch_page(url, timeout=30, budget=self.budget)
                response.raise_for_status()
                page_url = final_url(response, url)
                if not within_url_limits(page_url):
                    logging.warning(f"Skipping {url}: it redirects to an address too long or too deep to store")
                    continue
                document = page_document(
                    response.content,
                    response.headers.get("Content-Type"),
                    # Stored under the address it redirected to.
                    page_url,
                    include_host=include_host,
                    keep_links=self.keep_links,
                    # Each address was asked for: JSON there is wanted text.
                    explicit=True,
                )
                if document is not None:
                    # The worker matches the tree entry by any address that led to it.
                    note_requested_url(document, url)
                    try:
                        key = page_key(page_url)
                    except ValueError:
                        key = page_url
                    if key in by_key:
                        merge_requested_urls(by_key[key], document)
                        continue
                    by_key[key] = document
                    documents.append(document)
            except Exception as e:
                logging.error(f"Error processing URL {url}: {e}", exc_info=True)
                continue
        return dedupe_virtual_paths(documents)
