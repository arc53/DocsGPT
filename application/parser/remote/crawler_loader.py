import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from application.parser.remote.base import BaseRemote

class CrawlerLoader(BaseRemote):
    def __init__(self, limit=10):
        from langchain.document_loaders import WebBaseLoader
        self.loader = WebBaseLoader  # Initialize the document loader
        self.limit = limit  # Set the limit for the number of pages to scrape

    def load_data(self, url):
        # Check if the input is a list and if it is, use the first element
        if isinstance(url, list) and url:
            url = url[0]

        # Check if the URL scheme is provided, if not, assume http
        if not urlparse(url).scheme:
            url = "http://" + url

        visited_urls = set()  # Keep track of URLs that have been visited
        base_url = urlparse(url).scheme + "://" + urlparse(url).hostname  # Extract the base URL
        urls_to_visit = [url]  # List of URLs to be visited, starting with the initial URL
        loaded_content = []  # Store the loaded content from each URL

        # Continue crawling until there are no more URLs to visit
        while urls_to_visit:
            current_url = urls_to_visit.pop(0)  # Get the next URL to visit
            visited_urls.add(current_url)  # Mark the URL as visited

            # Try to load and process the content from the current URL
            try:
                response = requests.get(current_url)  # Fetch the content of the current URL
                response.raise_for_status()  # Raise an exception for HTTP errors
                loader = self.loader([current_url])  # Initialize the document loader for the current URL
                loaded_content.extend(loader.load())  # Load the content and add it to the loaded_content list
            except Exception as e:
                # Print an error message if loading or processing fails and continue with the next URL
                print(f"Error processing URL {current_url}: {e}")
                continue

            # Parse the HTML content to extract all links
            soup = BeautifulSoup(response.text, 'html.parser')
            all_links = [
                urljoin(current_url, a['href'])
                for a in soup.find_all('a', href=True)
                if base_url in urljoin(current_url, a['href'])  # Ensure links are from the same domain
            ]

            # Add new links to the list of URLs to visit if they haven't been visited yet
            urls_to_visit.extend([link for link in all_links if link not in visited_urls])
            urls_to_visit = list(set(urls_to_visit))  # Remove duplicate URLs

            # Stop crawling if the limit of pages to scrape is reached
            if self.limit is not None and len(visited_urls) >= self.limit:
                break

        return loaded_content  # Return the loaded content from all visited URLs
