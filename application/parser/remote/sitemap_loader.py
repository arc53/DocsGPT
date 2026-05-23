import logging
import re

import defusedxml.ElementTree as ET
from bs4 import BeautifulSoup

from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document
from application.core.url_validation import validate_url, SSRFError
from application.security.safe_url import UnsafeUserUrlError, pinned_request

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
            logging.error(f"URL validation failed: {e}")
            return []

        urls = self._extract_urls(sitemap_url)
        if not urls:
            print(f"No URLs found in the sitemap: {sitemap_url}")
            return []

        # Load content of extracted URLs
        documents = []
        processed_urls = 0  # Counter for processed URLs
        for url in urls:
            if self.limit is not None and processed_urls >= self.limit:
                break  # Stop processing if the limit is reached

            try:
                url = validate_url(url)
            except SSRFError as e:
                logging.error(f"URL validation failed for sitemap entry {url}: {e}")
                continue
            try:
                response = pinned_request("GET", url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                documents.append(
                    Document(
                        soup.get_text(separator="\n", strip=True),
                        extra_info={"source": url},
                    )
                )
                processed_urls += 1  # Increment the counter after processing each URL
            except Exception as e:
                logging.error(f"Error processing URL {url}: {e}", exc_info=True)
                continue

        return documents

    def _extract_urls(self, sitemap_url):
        try:
            response = pinned_request("GET", sitemap_url, timeout=30)
            response.raise_for_status()
        except UnsafeUserUrlError as e:
            print(f"URL validation failed for sitemap: {sitemap_url}. Error: {e}")
            return []
        except Exception as e:
            print(f"Failed to fetch sitemap: {sitemap_url}. Error: {e}")
            return []

        # Determine if this is a sitemap or a URL
        if self._is_sitemap(response):
            # It's a sitemap, so parse it and extract URLs
            return self._parse_sitemap(response.content)
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

    def _parse_sitemap(self, sitemap_content):
        # Remove namespaces
        sitemap_content = re.sub(' xmlns="[^"]+"', '', sitemap_content.decode('utf-8'), count=1)

        root = ET.fromstring(sitemap_content)

        urls = []
        for loc in root.findall('.//url/loc'):
            if not loc.text:
                continue
            urls.append(loc.text)

        # Check for nested sitemaps
        for sitemap in root.findall('.//sitemap/loc'):
            nested_sitemap_url = sitemap.text
            if not nested_sitemap_url:
                continue
            urls.extend(self._extract_urls(nested_sitemap_url))

        return urls
