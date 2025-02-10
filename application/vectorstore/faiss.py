import os

from langchain_community.vectorstores import FAISS

from application.core.settings import settings
from application.parser.schema.base import Document
from application.vectorstore.base import BaseVectorStore


def get_vectorstore(path: str) -> str:
    if path:
        vectorstore = os.path.join("application", "indexes", path)
    else:
        vectorstore = os.path.join("application")
    return vectorstore


class FaissStore(BaseVectorStore):
    def __init__(self, source_id: str, embeddings_key: str, docs_init=None):
        super().__init__()
        self.source_id = source_id
        self.path = get_vectorstore(source_id)
        self.embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        try:
            if docs_init:
                self.docsearch = FAISS.from_documents(docs_init, self.embeddings)
            else:
                self.docsearch = FAISS.load_local(
                    self.path, self.embeddings, allow_dangerous_deserialization=True
                )
        except Exception:
            raise

        self.assert_embedding_dimensions(self.embeddings)

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        return self.docsearch.save_local(*args, **kwargs)

    def delete_index(self, *args, **kwargs):
        return self.docsearch.delete(*args, **kwargs)

    def assert_embedding_dimensions(self, embeddings):
        """Check that the word embedding dimension of the docsearch index matches the dimension of the word embeddings used."""
        if (
            settings.EMBEDDINGS_NAME
            == "huggingface_sentence-transformers/all-mpnet-base-v2"
        ):
            word_embedding_dimension = getattr(embeddings, "dimension", None)
            if word_embedding_dimension is None:
                raise AttributeError(
                    "'dimension' attribute not found in embeddings instance."
                )

            docsearch_index_dimension = self.docsearch.index.d
            if word_embedding_dimension != docsearch_index_dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: embeddings.dimension ({word_embedding_dimension}) != docsearch index dimension ({docsearch_index_dimension})"
                )

    def get_chunks(self):
        chunks = []
        if self.docsearch:
            for doc_id, doc in self.docsearch.docstore._dict.items():
                chunk_data = {
                    "doc_id": doc_id,
                    "text": doc.page_content,
                    "metadata": doc.metadata,
                }
                chunks.append(chunk_data)
        return chunks

    def add_chunk(self, text, metadata=None):
        metadata = metadata or {}
        doc = Document(text=text, extra_info=metadata).to_langchain_format()
        doc_id = self.docsearch.add_documents([doc])
        self.save_local(self.path)
        return doc_id

    def delete_chunk(self, chunk_id):
        self.delete_index([chunk_id])
        self.save_local(self.path)
        return True
