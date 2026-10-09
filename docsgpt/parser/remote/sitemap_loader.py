import logging
import re
from typing import List, Optional, Set

import defusedxml.ElementTree as ET
from bs4 import BeautifulSoup
from defusedxml import DefusedXmlException

from docsgpt.parser.remote.base import (
    BaseRemote,
    dedupe_virtual_paths,
    spans_multiple_hosts,
    url_to_virtual_path,
)
from docsgpt.parser.schema.base import Document
from docsgpt.core.url_validation import validate_url, SSRFError
from docsgpt.security.safe_url import UnsafeUserUrlError, pinned_request

logger = logging.getLogger(__name__)

# How many levels of nested sitemap indexes to follow below the one the user
# gave. Real sites use one or two; past this it is a loop or a trap.
MAX_SITEMAP_DEPTH = 5


class SitemapLoader(BaseRemote):
    def __init__(self, limit=20):
        self.limit = limit  # Adding limit to control the number of URLs to process

    def load_data(self, inputs):
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

        # Load content of extracted URLs
        include_host = spans_multiple_hosts(urls)
        documents = []
        processed_urls = 0  # Counter for processed URLs
        for url in urls:
            if self.limit is not None and processed_urls >= self.limit:
                break  # Stop processing if the limit is reached

            try:
                url = validate_url(url)
            except SSRFError as e:
                logger.error(f"URL validation failed for sitemap entry {url}: {e}")
                continue
            try:
                response = pinned_request("GET", url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                documents.append(
                    Document(
                        soup.get_text(separator="\n", strip=True),
                        # Without file_path the worker had no tree key (no
                        # title, key or doc_id), so sitemap pages never
                        # appeared in the file tree.
                        extra_info={
                            "source": url,
                            "file_path": url_to_virtual_path(url, include_host),
                        },
                    )
                )
                processed_urls += 1  # Increment the counter after processing each URL
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}", exc_info=True)
                continue

        return dedupe_virtual_paths(documents)

    def _extract_urls(
        self, sitemap_url: str, visited: Optional[Set[str]] = None, depth: int = 0
    ) -> List[str]:
        """Fetch a sitemap (or page) URL and return the page URLs it lists.

        Each sitemap is fetched at most once per walk, and nested sitemap
        indexes are followed at most ``MAX_SITEMAP_DEPTH`` levels deep, so a
        sitemap that lists itself (or a ring of them) cannot loop.

        Args:
            sitemap_url: The sitemap or page URL to fetch.
            visited: Sitemap URLs already fetched in this walk; shared with
                the nested calls. ``None`` starts a new walk.
            depth: How many sitemap indexes deep this URL is.

        Returns:
            Page URLs found, or ``[sitemap_url]`` when it is not a sitemap.
        """
        visited = set() if visited is None else visited
        key = sitemap_url.strip()
        if key in visited:
            logger.warning(f"Skipping already-visited sitemap: {sitemap_url}")
            return []
        if depth > MAX_SITEMAP_DEPTH:
            logger.warning(
                f"Not following sitemap {sitemap_url}: nesting depth exceeds {MAX_SITEMAP_DEPTH}"
            )
            return []
        visited.add(key)

        try:
            response = pinned_request("GET", sitemap_url, timeout=30)
            response.raise_for_status()
        except UnsafeUserUrlError as e:
            logger.error(f"URL validation failed for sitemap: {sitemap_url}. Error: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch sitemap: {sitemap_url}. Error: {e}")
            return []

        # Determine if this is a sitemap or a URL
        if self._is_sitemap(response):
            # It's a sitemap, so parse it and extract URLs
            return self._parse_sitemap(response.content, visited, depth)
        else:
            # It's not a sitemap, return the URL itself
            return [sitemap_url]

    def _is_sitemap(self, response):
        content_type = response.headers.get('Content-Type', '')
        if 'xml' in content_type or response.url.endswith('.xml'):
            return True

        if '<sitemapindex' in response.text or '<urlset' in response.text:
            return True

        return False

    def _parse_sitemap(
        self, sitemap_content: bytes, visited: Optional[Set[str]] = None, depth: int = 0
    ) -> List[str]:
        """Return the page URLs in a sitemap, following nested sitemap indexes.

        Stops following child sitemaps once ``limit`` URLs have been found,
        and treats unparseable XML as an empty sitemap rather than failing
        the whole ingest.

        Args:
            sitemap_content: Raw sitemap XML.
            visited: Sitemap URLs already fetched in this walk.
            depth: How many sitemap indexes deep this sitemap is.

        Returns:
            Page URLs found in this sitemap and the children it was allowed to follow.
        """
        visited = set() if visited is None else visited
        try:
            # Remove namespaces
            text = re.sub(' xmlns="[^"]+"', '', sitemap_content.decode('utf-8'), count=1)
            root = ET.fromstring(text)
        except (ET.ParseError, DefusedXmlException, UnicodeDecodeError) as e:
            logger.warning(f"Skipping sitemap that could not be parsed: {e}")
            return []

        urls = []
        for loc in root.findall('.//url/loc'):
            if not loc.text or not loc.text.strip():
                continue
            urls.append(loc.text.strip())

        # Check for nested sitemaps
        for sitemap in root.findall('.//sitemap/loc'):
            if self.limit is not None and len(urls) >= self.limit:
                break
            nested_sitemap_url = (sitemap.text or "").strip()
            if not nested_sitemap_url:
                continue
            urls.extend(self._extract_urls(nested_sitemap_url, visited, depth + 1))

        return urls
