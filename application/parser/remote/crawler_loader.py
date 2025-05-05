import logging
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document
from langchain_community.document_loaders import WebBaseLoader

class CrawlerLoader(BaseRemote):
    def __init__(self, limit=10):
        self.loader = WebBaseLoader  # Initialize the document loader
        self.limit = limit  # Set the limit for the number of pages to scrape

    def load_data(self, inputs):
        url = inputs
        if isinstance(url, list) and url:
            url = url[0]

        # Check if the URL scheme is provided, if not, assume http
        if not urlparse(url).scheme:
            url = "http://" + url

        visited_urls = set()
        base_url = urlparse(url).scheme + "://" + urlparse(url).hostname
        urls_to_visit = [url]
        loaded_content = []

        while urls_to_visit:
            current_url = urls_to_visit.pop(0)
            visited_urls.add(current_url)

            try:
                response = requests.get(current_url)
                response.raise_for_status()
                loader = self.loader([current_url])
                docs = loader.load()
                # Convert the loaded documents to your Document schema
                for doc in docs:
                    loaded_content.append(
                        Document(
                            doc.page_content,
                            extra_info=doc.metadata
                        )
                    )
            except Exception as e:
                logging.error(f"Error processing URL {current_url}: {e}", exc_info=True)
                continue

            # Parse the HTML content to extract all links
            soup = BeautifulSoup(response.text, 'html.parser')
            all_links = [
                urljoin(current_url, a['href'])
                for a in soup.find_all('a', href=True)
                if base_url in urljoin(current_url, a['href'])
            ]

            # Add new links to the list of URLs to visit if they haven't been visited yet
            urls_to_visit.extend([link for link in all_links if link not in visited_urls])
            urls_to_visit = list(set(urls_to_visit))

            # Stop crawling if the limit of pages to scrape is reached
            if self.limit is not None and len(visited_urls) >= self.limit:
                break

        return loaded_content
