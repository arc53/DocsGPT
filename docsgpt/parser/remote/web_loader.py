import logging
from typing import List, Optional, Union

from docsgpt.core.url_validation import SSRFError, validate_url
from docsgpt.parser.remote.base import (
    BaseRemote,
    dedupe_virtual_paths,
    spans_multiple_hosts,
)
from docsgpt.parser.remote.page_content import FetchBudget, fetch_page, final_url, page_document
from docsgpt.parser.schema.base import Document

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*"
    ";q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class WebLoader(BaseRemote):
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
            redirect led to (and ``requested_url`` the address asked for,
            only when the two differ); a blocked address, a failed fetch or a
            response with no text is skipped.
        """
        urls = inputs
        if isinstance(urls, str):
            urls = [urls]
        valid_urls = []
        for url in urls:
            try:
                valid_urls.append(validate_url(url))
            except SSRFError as e:
                logging.warning(
                    f"Skipping URL due to SSRF validation failure: {url} - {e}"
                )
        include_host = spans_multiple_hosts(valid_urls)
        documents = []
        for url in valid_urls:
            if self.budget is not None and not self.budget.take():
                logging.warning(f"Fetch budget spent; not fetching {url}")
                break
            try:
                response = fetch_page(url, headers=headers, timeout=30, budget=self.budget)
                response.raise_for_status()
                page_url = final_url(response, url)
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
                    if page_url != url:
                        # The worker matches the tree entry by either address.
                        document.extra_info["requested_url"] = url
                    documents.append(document)
            except Exception as e:
                logging.error(f"Error processing URL {url}: {e}", exc_info=True)
                continue
        return dedupe_virtual_paths(documents)
