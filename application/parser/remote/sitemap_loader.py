import requests
import re  # Import regular expression library
import xml.etree.ElementTree as ET
from application.parser.remote.base import BaseRemote

class SitemapLoader(BaseRemote):
    def __init__(self, limit=20):
        from langchain.document_loaders import WebBaseLoader
        self.loader = WebBaseLoader
        self.limit = limit  # Adding limit to control the number of URLs to process

    def load_data(self, sitemap_url):
        # Check if the input is a list and if it is, use the first element
        if isinstance(sitemap_url, list) and sitemap_url:
            url = sitemap_url[0]
            
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
                loader = self.loader([url])
                documents.extend(loader.load())
                processed_urls += 1  # Increment the counter after processing each URL
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
                continue

        return documents

    def _extract_urls(self, sitemap_url):
        try:
            response = requests.get(sitemap_url)
            response.raise_for_status()  # Raise an exception for HTTP errors
        except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as e:
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
            urls.append(loc.text)

        # Check for nested sitemaps
        for sitemap in root.findall('.//sitemap/loc'):
            nested_sitemap_url = sitemap.text
            urls.extend(self._extract_urls(nested_sitemap_url))

        return urls
