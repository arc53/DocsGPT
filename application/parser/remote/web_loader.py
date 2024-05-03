from application.parser.remote.base import BaseRemote
from langchain_community.document_loaders import WebBaseLoader

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
    def __init__(self):
        self.loader = WebBaseLoader

    def load_data(self, inputs):
        urls = inputs
        if isinstance(urls, str):
            urls = [urls]
        documents = []
        for url in urls:
            try:
                loader = self.loader([url], header_template=headers)
                documents.extend(loader.load())
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
                continue
        return documents
