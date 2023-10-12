import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from application.parser.remote.base import BaseRemote

class CrawlerLoader(BaseRemote):
    def __init__(self):
        from langchain.document_loaders import WebBaseLoader
        self.loader = WebBaseLoader

    def load_data(self, url):
        # Fetch the content of the initial URL
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Failed to fetch initial URL: {url}")
            return None

        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract the base URL to ensure we only fetch URLs from the same domain
        base_url = urlparse(url).scheme + "://" + urlparse(url).hostname

        # Extract all links from the HTML content
        all_links = [a['href'] for a in soup.find_all('a', href=True)]

        # Filter out the links that lead to a different domain
        same_domain_links = [urljoin(base_url, link) for link in all_links if base_url in urljoin(base_url, link)]

        # Remove duplicates
        same_domain_links = list(set(same_domain_links))

        #TODO: Optimize this section to parse pages as they are being crawled
        loaded_content = self.loader(same_domain_links).load()

        return loaded_content
