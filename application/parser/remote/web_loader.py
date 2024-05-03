from application.parser.remote.base import BaseRemote
from langchain_community.document_loaders import WebBaseLoader


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
                loader = self.loader(
                    [url], header_template={"User-Agent": "Mozilla/5.0"}
                )
                documents.extend(loader.load())
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
                continue
        return documents
