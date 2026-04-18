import logging
from application.core.url_validation import SSRFError, validate_url
from application.parser.remote.base import BaseRemote
from application.parser.schema.base import Document
from application.core.url_validation import validate_url, SSRFError
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
                url = validate_url(url)
            except SSRFError as e:
                logging.warning(
                    f"Skipping URL due to SSRF validation failure: {url} - {e}"
                )
                continue
            try:
                loader = self.loader([url], header_template=headers)
                loaded_docs = loader.load()
                for doc in loaded_docs:
                    documents.append(
                        Document(
                            doc.page_content,
                            extra_info=doc.metadata,
                        )
                    )
            except Exception as e:
                logging.error(f"Error processing URL {url}: {e}", exc_info=True)
                continue
        return documents
