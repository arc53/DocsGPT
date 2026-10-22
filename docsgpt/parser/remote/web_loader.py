import logging

from docsgpt.core.url_validation import SSRFError, validate_url
from docsgpt.parser.remote.base import (
    BaseRemote,
    dedupe_virtual_paths,
    spans_multiple_hosts,
)
from docsgpt.parser.remote.page_content import page_document
from docsgpt.security.safe_url import pinned_request

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
    def load_data(self, inputs):
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
            try:
                response = pinned_request("GET", url, headers=headers, timeout=30)
                response.raise_for_status()
                document = page_document(
                    response.content,
                    response.headers.get("Content-Type"),
                    url,
                    include_host=include_host,
                )
                if document is not None:
                    documents.append(document)
            except Exception as e:
                logging.error(f"Error processing URL {url}: {e}", exc_info=True)
                continue
        return dedupe_virtual_paths(documents)
