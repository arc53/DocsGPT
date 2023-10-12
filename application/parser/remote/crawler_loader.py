import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from application.parser.remote.base import BaseRemote

class CrawlerLoader(BaseRemote):
    def __init__(self, limit=10):
        from langchain.document_loaders import WebBaseLoader
        self.loader = WebBaseLoader
        #No pages scraped limit, set None for no limit
        self.limit = limit

    def load_data(self, url):
        # Create a set to store visited URLs to avoid revisiting the same page
        visited_urls = set()

        # Extract the base URL to ensure we only fetch URLs from the same domain
        base_url = urlparse(url).scheme + "://" + urlparse(url).hostname

        # Initialize a list with the initial URL
        urls_to_visit = [url]

        while urls_to_visit:
            current_url = urls_to_visit.pop(0)
            visited_urls.add(current_url)

            # Fetch the content of the current URL
            response = requests.get(current_url)
            if response.status_code != 200:
                print(f"Failed to fetch URL: {current_url}")
                continue

            # Parse the HTML content
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract all links from the HTML content
            all_links = [urljoin(current_url, a['href']) for a in soup.find_all('a', href=True) if base_url in urljoin(current_url, a['href'])]

            # Add the new links to the urls_to_visit list if they haven't been visited yet
            urls_to_visit.extend([link for link in all_links if link not in visited_urls])

            # Remove duplicates
            urls_to_visit = list(set(urls_to_visit))

            # Stop if the limit is reached
            if self.limit is not None and len(visited_urls) >= self.limit:
                break

        #TODO: Optimize this section to parse pages as they are being crawled
        loaded_content = self.loader(list(visited_urls)).load()

        return loaded_content