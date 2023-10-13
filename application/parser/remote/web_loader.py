from application.parser.remote.base import BaseRemote

class WebLoader(BaseRemote):
    def __init__(self):
        from langchain.document_loaders import WebBaseLoader
        self.loader = WebBaseLoader

    def load_data(self, inputs):
        urls = inputs['data']

        if isinstance(urls, str):
            urls = [urls] # Convert string to list if a single URL is passed

        documents = []
        for url in urls:
            try:
                loader = self.loader([url])  # Process URLs one by one
                documents.extend(loader.load())
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
                continue  # Continue with the next URL if an error occurs
        return documents