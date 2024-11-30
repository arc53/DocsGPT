from langchain_community.vectorstores import FAISS
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
import os
import sys


def get_vectorstore(path: str) -> str:
    if path:
        vectorstore = os.path.join("application", "indexes", path)
    else:
        vectorstore = os.path.join("application")
    return vectorstore


class FaissStore(BaseVectorStore):
    def __init__(self, source_id: str, embeddings_key: str, docs_init=None):
        super().__init__()
        self.path = get_vectorstore(source_id)
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        print(f"Embeddings: {embeddings}")
        print(f"Dimension: {embeddings.dimension}")
        try:
            if docs_init:
                print(f"Docs init on: {docs_init}", file=sys.stderr)
                print(f"path: {self.path}", file=sys.stderr)
                self.docsearch = FAISS.from_documents(docs_init, embeddings)
                print(f"FAISS instance created with documents: {self.docsearch}", file=sys.stderr)
                print(f"FAISS Index Total Vectors: {self.docsearch.index.ntotal}", file=sys.stderr)
                if self.docsearch.index.ntotal == 0:
                    print("FAISS index is empty. No data to search.", file=sys.stderr)
            else:
                print(f"Docs init off: {docs_init}", file=sys.stderr)
                print(f"path: {self.path}", file=sys.stderr)
                self.docsearch = FAISS.load_local(
                    self.path, embeddings, allow_dangerous_deserialization=True
                )
                print(f"FAISS instance loaded from local path: {self.docsearch}", file=sys.stderr)
                print(f"FAISS Index Total Vectors: {self.docsearch.index.ntotal}", file=sys.stderr)
                if self.docsearch.index.ntotal == 0:
                    print("FAISS index is empty. No data to search.", file=sys.stderr)
        except Exception:
            raise

        self.assert_embedding_dimensions(embeddings)

    def search(self, *args, **kwargs):
        print(f"Performing FAISS search with args: {args}, kwargs: {kwargs}", file=sys.stderr)
        results = self.docsearch.similarity_search(*args, **kwargs)
        print(f"FAISS search results: {results}", file=sys.stderr)
        return results

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        return self.docsearch.save_local(*args, **kwargs)

    def delete_index(self, *args, **kwargs):
        return self.docsearch.delete(*args, **kwargs)

    def assert_embedding_dimensions(self, embeddings):
        """Check that the word embedding dimension of the docsearch index matches the dimension of the word embeddings used."""
        if settings.EMBEDDINGS_NAME == "openai/clip-vit-base-patch16":
            word_embedding_dimension = getattr(embeddings, "dimension", None)
            if word_embedding_dimension is None:
                raise AttributeError(
                    "'dimension' attribute not found in embeddings instance."
                )

            docsearch_index_dimension = self.docsearch.index.d
            # Log dimensions for debugging
            import sys

            print(
                f"Validating embedding dimensions: "
                f"Model dimension = {word_embedding_dimension}, Index dimension = {docsearch_index_dimension}",
                file=sys.stderr,
            )
            if word_embedding_dimension != docsearch_index_dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: embeddings.dimension ({word_embedding_dimension}) != docsearch index dimension ({docsearch_index_dimension})"
                )
