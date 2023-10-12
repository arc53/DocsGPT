from application.vectorstore.base import BaseVectorStore
from langchain.vectorstores import FAISS
from application.core.settings import settings

HUGGINGFACE_MODEL_NAME = "huggingface_sentence-transformers/all-mpnet-base-v2"
class FaissStore(BaseVectorStore):

    def __init__(self, path, embeddings_key, docs_init=None):
        super().__init__()
        self.path = path
        if docs_init:
            self.docsearch = FAISS.from_documents(
                docs_init, self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
            )
        else:
            embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
            self.docsearch = FAISS.load_local(
                self.path, embeddings
            )
            
            # Check that the word_embedding_dimension of the index matches the word_embedding_dimension of the embeddings
            if settings.EMBEDDINGS_NAME == HUGGINGFACE_MODEL_NAME:
                try:
                    word_embedding_dimension = embeddings.client[1].word_embedding_dimension
                except AttributeError as e:
                    raise AttributeError("word_embedding_dimension not found in embeddings.client[1]") from e
                if word_embedding_dimension != self.docsearch.index.d:
                    raise ValueError("word_embedding_dimension != docsearch_index_word_embedding_dimension")

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)
    
    def save_local(self, *args, **kwargs):
        return self.docsearch.save_local(*args, **kwargs)
