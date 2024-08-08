from typing import List, Optional
from langchain_community.vectorstores.milvus import Milvus

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore


class MilvusStore(BaseVectorStore):
    def __init__(self, path: str = "", embeddings_key: str = "embeddings"):
        super().__init__()
        if path:
            connection_args ={
                "uri": path,
                "tpken": settings.MILVUS_TOKEN,
            }
        else:
            connection_args = {
                "uri": settings.MILVUS_URL,
                'token': settings.MILVUS_TOKEN,
            }
        self._docsearch = Milvus(
            embedding_function=self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key),
            collection_name=settings.COLLECTION_NAME,
            connection_args=connection_args,
            drop_old=True,
        )

    def search(self, question, k=2, *args, **kwargs):
        return self._docsearch.similarity_search(query=question, k=k, *args, **kwargs)

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]], *args, **kwargs):
        return self._docsearch.add_texts(texts=texts, metadatas=metadatas, *args, **kwargs)

    def save_local(self, *args, **kwargs):
        pass

    def delete_index(self, *args, **kwargs):
        pass
