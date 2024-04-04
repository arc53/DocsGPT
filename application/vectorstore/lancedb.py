from langchain_community.vectorstores import LanceDB
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings

class LancedbStore(BaseVectorStore):

    def __init__(self, path, embeddings_key, docs_init=None):
        super().__init__()
        self.path = path
        self.embeddings_key = embeddings_key
        self.docsearch = None  
        
        # Load embeddings based on a given key
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key)
        
        # Initialize LanceDB if docs_init is provided and has content
        if docs_init:
            self.docsearch = LanceDB.from_documents(docs_init, embeddings)
        else:
            # Log or handle the absence of docs_init appropriately
            print(f"No initial documents provided for LanceDB initialization at {path}.")
    
    
    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        pass

    def delete_index(self, *args, **kwargs):
        pass
