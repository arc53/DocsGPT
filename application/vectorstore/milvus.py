from typing import List, Optional
from uuid import uuid4


from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore


class MilvusStore(BaseVectorStore):
    def __init__(self, source_id: str = "", embeddings_key: str = "embeddings"):
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
        self._source_id = source_id

    def search(self, question, k=2, *args, **kwargs):
        expr = f"source_id == '{self._source_id}'"
        return self._docsearch.similarity_search(query=question, k=k, expr=expr, *args, **kwargs)
    
    def search_with_scores(self, query: str, k: int, *args, **kwargs):
        expr = f"source_id == '{self._source_id}'"
        docs_and_distances = self._docsearch.similarity_search_with_score(query, k, expr=expr, *args, **kwargs)
        docs_with_scores = []
        for doc, distance in docs_and_distances:
            similarity = 1.0 - distance
            docs_with_scores.append((doc, max(0, similarity)))
        
        return docs_with_scores

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]], *args, **kwargs):
        ids = [str(uuid4()) for _ in range(len(texts))]

        return self._docsearch.add_texts(texts=texts, metadatas=metadatas, ids=ids, *args, **kwargs)

    def save_local(self, *args, **kwargs):
        pass

    def delete_index(self, *args, **kwargs):
        pass
