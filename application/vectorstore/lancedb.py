from langchain_community.vectorstores import LanceDB
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings

class LancedbStore(BaseVectorStore):

    def __init__(self, path, embeddings_key, docs_init=None):
        super().__init__()
        self.path = path
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        if docs_init:
            self.docsearch = LanceDB.from_documents(docs_init, embeddings)

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        pass

    def delete_index(self, *args, **kwargs):
        pass
