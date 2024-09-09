from langchain_community.vectorstores import FAISS
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
import os

def get_vectorstore(path):
    if path:
        vectorstore = "indexes/"+path
        vectorstore = os.path.join("application", vectorstore)
    else:
        vectorstore = os.path.join("application")

    return vectorstore

class FaissStore(BaseVectorStore):

    def __init__(self, source_id, embeddings_key, docs_init=None):
        super().__init__()
        self.path = get_vectorstore(source_id)
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        if docs_init:
            self.docsearch = FAISS.from_documents(
                docs_init, embeddings
            )
        else:
            self.docsearch = FAISS.load_local(
                self.path, embeddings, 
                allow_dangerous_deserialization=True
            )
        self.assert_embedding_dimensions(embeddings)

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        return self.docsearch.save_local(*args, **kwargs)

    def delete_index(self, *args, **kwargs):
        return self.docsearch.delete(*args, **kwargs)

    def assert_embedding_dimensions(self, embeddings):
        """
        Check that the word embedding dimension of the docsearch index matches
        the dimension of the word embeddings used 
        """
        if settings.EMBEDDINGS_NAME == "huggingface_sentence-transformers/all-mpnet-base-v2":
            try:
                word_embedding_dimension = embeddings.dimension
            except AttributeError as e:
                raise AttributeError("'dimension' attribute not found in embeddings instance. Make sure the embeddings object is properly initialized.") from e
            docsearch_index_dimension = self.docsearch.index.d
            if word_embedding_dimension != docsearch_index_dimension:
                raise ValueError(f"Embedding dimension mismatch: embeddings.dimension ({word_embedding_dimension}) " +
                                 f"!= docsearch index dimension ({docsearch_index_dimension})")