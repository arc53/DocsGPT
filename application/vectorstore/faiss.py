from application.vectorstore.base import BaseVectorStore
from langchain import FAISS
from application.core.settings import settings

class FaissStore(BaseVectorStore):

    def __init__(self, path, embeddings_key):
        super().__init__()
        self.path = path
        self.docsearch = FAISS.load_local(
            self.path, self._get_docsearch(settings.EMBEDDINGS_NAME, settings.EMBEDDINGS_KEY)
        )

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)
