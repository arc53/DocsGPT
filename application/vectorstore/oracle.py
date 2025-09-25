import os
from typing import List, Optional

from langchain_community.vectorstores import OracleHybridSearch  # Adjust if OracleVectorStore exists
from application.vectorstore.base import BaseVectorStore, EmbeddingsSingleton
from langchain_core.documents import Document

class OracleVectorStore(BaseVectorStore):
    def __init__(self, embeddings_name: str = "openai_text-embedding-ada-002", embeddings_key: Optional[str] = None):
        super().__init__()
        self.embeddings = self._get_embeddings(embeddings_name, embeddings_key)
        self.connection_string = os.getenv("ORACLE_CONNECTION_STRING")
        if not self.connection_string:
            raise ValueError("ORACLE_CONNECTION_STRING env var required")
        self.vectorstore = OracleHybridSearch(
            connection_string=self.connection_string,
            embedding=self.embeddings
        )

    def search(self, query: str, k: int = 4, **kwargs) -> List[Document]:
        """Search for similar documents/chunks."""
        return self.vectorstore.similarity_search(query, k=k, **kwargs)

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None, **kwargs) -> List[str]:
        """Add texts with their embeddings to the vectorstore."""
        return self.vectorstore.add_texts(texts, metadatas=metadatas, **kwargs)

    def delete_index(self, **kwargs):
        """Delete the entire index/collection."""
        self.vectorstore.delete_collection()  # Adjust based on LangChain API

    def save_local(self, **kwargs):
        """Save vectorstore to local storage (optional, may not apply to Oracle)."""
        raise NotImplementedError("Local save not supported for OracleVectorStore")

    def get_chunks(self, **kwargs) -> List[Document]:
        """Get all chunks from the vectorstore."""
        raise NotImplementedError("get_chunks not implemented for OracleVectorStore")

    def add_chunk(self, text: str, metadata: Optional[dict] = None, **kwargs) -> str:
        """Add a single chunk to the vectorstore."""
        return self.add_texts([text], [metadata])[0] if metadata else self.add_texts([text])[0]

    def delete_chunk(self, chunk_id: str, **kwargs):
        """Delete a specific chunk (if supported by Oracle)."""
        raise NotImplementedError("delete_chunk not implemented for OracleVectorStore")