import requests
import xml.etree.ElementTree as ET
from application.parser.remote.base import BaseRemote

class SitemapLoader(BaseRemote):
    def __init__(self):
        from langchain.document_loaders import WebBaseLoader
        self.loader = WebBaseLoader

    def load_data(self, sitemap_url):
        # Fetch the sitemap content
        response = requests.get(sitemap_url)
        if response.status_code != 200:
            print(f"Failed to fetch sitemap: {sitemap_url}")
            return None

        # Parse the sitemap XML
        root = ET.fromstring(response.content)

        # Extract URLs from the sitemap
        # The namespace with "loc" tag might be needed to extract URLs
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = [loc.text for loc in root.findall('s:url/s:loc', ns)]

        # Use your existing loader to load content of extracted URLs
        loader = self.loader(urls)
        return loader.load()