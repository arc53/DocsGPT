from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_community.vectorstores.utils import DistanceStrategy

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore


class OracleVectorStore(BaseVectorStore):
    """Oracle Database vector store integration using LangChain's OracleVS."""

    def __init__(self, source_id: str, embeddings_key: str, docs_init=None):
        super().__init__()
        self.source_id = source_id
        self.embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self.table_name = f"docsGPT_{source_id}".replace("-", "_")

        import oracledb

        self.connection = oracledb.connect(
            user=settings.ORACLE_USER,
            password=settings.ORACLE_PASSWORD,
            dsn=settings.ORACLE_DSN,
        )

        if docs_init:
            self.docsearch = OracleVS.from_documents(
                docs_init,
                self.embeddings,
                client=self.connection,
                table_name=self.table_name,
                distance_strategy=DistanceStrategy.COSINE,
            )
        else:
            self.docsearch = OracleVS(
                client=self.connection,
                embedding_function=self.embeddings,
                table_name=self.table_name,
                distance_strategy=DistanceStrategy.COSINE,
            )

    def search(self, *args, **kwargs):
        return self.docsearch.similarity_search(*args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self.docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        # Oracle persists automatically, no local save needed
        pass

    def delete_index(self, *args, **kwargs):
        return self.docsearch.delete(*args, **kwargs)

    def get_chunks(self):
        return []

    def add_chunk(self, text, metadata=None):
        metadata = metadata or {}
        return self.docsearch.add_texts([text], metadatas=[metadata])

    def delete_chunk(self, chunk_id):
        return self.delete_index([chunk_id])