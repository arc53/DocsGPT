from typing import List, Optional
from uuid import uuid4


from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore


class MilvusStore(BaseVectorStore):
    def __init__(self, path: str = "", embeddings_key: str = "embeddings"):
        super().__init__()
        from langchain_milvus import Milvus

        connection_args = {
            "uri": settings.MILVUS_URI,
            "token": settings.MILVUS_TOKEN,
        }
        self._docsearch = Milvus(
            embedding_function=self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key),
            collection_name=settings.MILVUS_COLLECTION_NAME,
            connection_args=connection_args,
        )
        self._path = path

    def search(self, question, k=2, *args, **kwargs):
        return self._docsearch.similarity_search(query=question, k=k, filter={"path": self._path} *args, **kwargs)

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]], *args, **kwargs):
        ids = [str(uuid4()) for _ in range(len(texts))]

        return self._docsearch.add_texts(texts=texts, metadatas=metadatas, ids=ids, *args, **kwargs)

    def save_local(self, *args, **kwargs):
        pass

    def delete_index(self, *args, **kwargs):
        pass
