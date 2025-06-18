import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from application.parser.remote.base import BaseRemote
import re
from markdownify import markdownify
from application.parser.schema.base import Document
import tldextract

class CrawlerLoader(BaseRemote):
    def __init__(self, limit=10, allow_subdomains=False):
        """
        Given a URL crawl web pages up to `self.limit`,
        convert HTML content to Markdown, and returning a list of Document objects.

        :param limit: The maximum number of pages to crawl.
        :param allow_subdomains: If True, crawl pages on subdomains of the base domain.
        """
        self.limit = limit
        self.allow_subdomains = allow_subdomains
        self.session = requests.Session()

    def load_data(self, inputs):
        url = inputs
        if isinstance(url, list) and url:
            url = url[0]

        # Ensure the URL has a scheme (if not, default to http)
        if not urlparse(url).scheme:
            url = "http://" + url

        # Keep track of visited URLs to avoid revisiting the same page
        visited_urls = set()

        # Determine the base domain for link filtering using tldextract
        base_domain = self._get_base_domain(url)
        urls_to_visit = {url}
        documents = []

        while urls_to_visit:
            current_url = urls_to_visit.pop()

            # Skip if already visited
            if current_url in visited_urls:
                continue
            visited_urls.add(current_url)

            # Fetch the page content
            html_content = self._fetch_page(current_url)
            if html_content is None:
                continue

            # Convert the HTML to Markdown for cleaner text formatting
            title, language, processed_markdown = self._process_html_to_markdown(html_content, current_url)
            if processed_markdown:
                # Create a Document for each visited page
                documents.append(
                    Document(
                        processed_markdown,  # content
                        None,  # doc_id
                        None,  # embedding
                        {"source": current_url, "title": title, "language": language} # extra_info
                    )
                )

            # Extract links and filter them according to domain rules
            new_links = self._extract_links(html_content, current_url)
            filtered_links = self._filter_links(new_links, base_domain)

            # Add any new, not-yet-visited links to the queue
            urls_to_visit.update(link for link in filtered_links if link not in visited_urls)

            # If we've reached the limit, stop crawling
            if self.limit is not None and len(visited_urls) >= self.limit:
                break

        return documents

    def _fetch_page(self, url):
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Error fetching URL {url}: {e}")
            return None

    def _process_html_to_markdown(self, html_content, current_url):
        soup = BeautifulSoup(html_content, 'html.parser')
        title_tag = soup.find('title')
        title = title_tag.text.strip() if title_tag else "No Title"

        # Extract language
        language_tag = soup.find('html')
        language = language_tag.get('lang', 'en') if language_tag else "en"

        markdownified = markdownify(html_content, heading_style="ATX", newline_style="BACKSLASH")
        # Reduce sequences of more than two newlines to exactly three
        markdownified = re.sub(r'\n{3,}', '\n\n\n', markdownified)
        return title, language, markdownified

    def _extract_links(self, html_content, current_url):
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            full_url = urljoin(current_url, a['href'])
            links.append((full_url, a.text.strip()))
        return links

    def _get_base_domain(self, url):
        extracted = tldextract.extract(url)
        # Reconstruct the domain as domain.suffix
        base_domain = f"{extracted.domain}.{extracted.suffix}"
        return base_domain

    def _filter_links(self, links, base_domain):
        """
        Filter the extracted links to only include those that match the crawling criteria:
        - If allow_subdomains is True, allow any link whose domain ends with the base_domain.
        - If allow_subdomains is False, only allow exact matches of the base_domain.
        """
        filtered = []
        for link, _ in links:
            parsed_link = urlparse(link)
            if not parsed_link.netloc:
                continue

            extracted = tldextract.extract(parsed_link.netloc)
            link_base = f"{extracted.domain}.{extracted.suffix}"

            if self.allow_subdomains:
                # For subdomains: sub.example.com ends with example.com
                if link_base == base_domain or link_base.endswith("." + base_domain):
                    filtered.append(link)
            else:
                # Exact domain match
                if link_base == base_domain:
                    filtered.append(link)
        return filtered