from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings


class QdrantStore(BaseVectorStore):
    def __init__(self, source_id: str = "", embeddings_key: str = "embeddings"):
        from qdrant_client import models
        from langchain_community.vectorstores.qdrant import Qdrant

        self._filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.source_id",
                    match=models.MatchValue(value=source_id.replace("application/indexes/", "").rstrip("/")),
                )
            ]
        )

        self._docsearch = Qdrant.construct_instance(
            ["TEXT_TO_OBTAIN_EMBEDDINGS_DIMENSION"],
            embedding=self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key),
            collection_name=settings.QDRANT_COLLECTION_NAME,
            location=settings.QDRANT_LOCATION,
            url=settings.QDRANT_URL,
            port=settings.QDRANT_PORT,
            grpc_port=settings.QDRANT_GRPC_PORT,
            https=settings.QDRANT_HTTPS,
            prefer_grpc=settings.QDRANT_PREFER_GRPC,
            api_key=settings.QDRANT_API_KEY,
            prefix=settings.QDRANT_PREFIX,
            timeout=settings.QDRANT_TIMEOUT,
            path=settings.QDRANT_PATH,
            distance_func=settings.QDRANT_DISTANCE_FUNC,
        )

    def search(self, *args, **kwargs):
        return self._docsearch.similarity_search(filter=self._filter, *args, **kwargs)
    
    def search_with_scores(self, query: str, k: int, *args, **kwargs):
        return self._docsearch.similarity_search_with_score(query=query, k=k, filter=self._filter, *args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self._docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        pass

    def delete_index(self, *args, **kwargs):
        return self._docsearch.client.delete(
            collection_name=settings.QDRANT_COLLECTION_NAME, points_selector=self._filter
        )
