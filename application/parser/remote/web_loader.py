from application.parser.remote.base import BaseRemote

class WebLoader(BaseRemote):
    def __init__(self):
        from langchain.document_loaders import WebBaseLoader
        self.loader = WebBaseLoader

    def load_data(self, urls):
        loader = self.loader(urls)
        return loader.load()