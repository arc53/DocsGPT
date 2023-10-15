from application.vectorstore.base import BaseVectorStore
from langchain.vectorstores import FAISS
from application.core.settings import settings

class FaissStore(BaseVectorStore):

    def __init__(self, path, embeddings_key, docs_init=None):
        super().__init__()
        self.path = path
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        if docs_init:
            self.docsearch = FAISS.from_documents(
                docs_init, embeddings
            )
        else:
            self.docsearch = FAISS.load_local(
                self.path, embeddings
            )
        self.assert_embedding_dimensions(embeddings)

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)
    
    def save_local(self, *args, **kwargs):
        return self.docsearch.save_local(*args, **kwargs)

    def assert_embedding_dimensions(self, embeddings, *args, **kwargs):
        """
        Check that the word embedding dimension of the docsearch index matches
        the dimension of the word embeddings used 
        """
        if settings.EMBEDDINGS_NAME == "huggingface_sentence-transformers/all-mpnet-base-v2":
            try:
                word_embedding_dimension = embeddings.client[1].word_embedding_dimension
            except AttributeError as e:
                raise AttributeError("word_embedding_dimension not found in embeddings.client[1]") from e
            docsearch_index_dimension = self.docsearch.index.d
            if word_embedding_dimension != docsearch_index_dimension:
                raise ValueError(f"word_embedding_dimension ({word_embedding_dimension}) " +
                                 f"!= docsearch_index_word_embedding_dimension ({docsearch_index_dimension})")

