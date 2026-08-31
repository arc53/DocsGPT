import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document


class QdrantStore(BaseVectorStore):
    """Vector store backed by Qdrant through the native ``qdrant-client``.

    Points carry a ``page_content`` payload plus a nested ``metadata`` object;
    every read is filtered to the store's ``source_id`` so one collection can
    hold many sources.
    """

    score_kind = "cosine_similarity"

    def __init__(self, source_id: str = "", embeddings_key: str = "embeddings"):
        super().__init__()
        from qdrant_client import QdrantClient, models

        self._models = models
        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        self._collection = settings.QDRANT_COLLECTION_NAME
        self._embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        self._filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.source_id",
                    match=models.MatchValue(value=self._source_id),
                )
            ]
        )
        self._client = QdrantClient(**self._client_kwargs())
        self._ensure_collection()

    @staticmethod
    def _client_kwargs() -> Dict[str, Any]:
        """Build ``QdrantClient`` kwargs, dropping unset optional settings.

        ``location``, ``url`` and ``path`` are mutually exclusive in
        qdrant-client, so only the ones actually configured are passed.
        """
        kwargs: Dict[str, Any] = {
            "prefer_grpc": settings.QDRANT_PREFER_GRPC,
            "grpc_port": settings.QDRANT_GRPC_PORT,
        }
        optional = {
            "location": settings.QDRANT_LOCATION,
            "url": settings.QDRANT_URL,
            "host": settings.QDRANT_HOST,
            "port": settings.QDRANT_PORT,
            "https": settings.QDRANT_HTTPS,
            "api_key": settings.QDRANT_API_KEY,
            "prefix": settings.QDRANT_PREFIX,
            "timeout": settings.QDRANT_TIMEOUT,
            "path": settings.QDRANT_PATH,
        }
        kwargs.update({k: v for k, v in optional.items() if v is not None})
        return kwargs

    def _dimension(self) -> int:
        """Resolve the embedding width, probing the model when unset."""
        dimension = getattr(self._embeddings, "dimension", None)
        if not dimension:
            dimension = len(self._embeddings.embed_query("dimension probe"))
        return dimension

    def _ensure_collection(self) -> None:
        """Create the collection and the source_id payload index if missing."""
        models = self._models
        try:
            if not self._client.collection_exists(self._collection):
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=models.VectorParams(
                        size=self._dimension(),
                        distance=models.Distance[settings.QDRANT_DISTANCE_FUNC.upper()],
                    ),
                )
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name="metadata.source_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            # A concurrent worker may have created either object first.
            if "already exists" not in str(e).lower():
                logging.warning("Qdrant collection setup: %s", e)

    @staticmethod
    def _to_document(payload: Dict[str, Any]) -> Document:
        payload = payload or {}
        return Document(
            page_content=payload.get("page_content", ""),
            metadata=payload.get("metadata") or {},
        )

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        """Return the ``k`` nearest chunks for ``question``."""
        return [doc for doc, _ in self.search_with_scores(question, k, *args, **kwargs)]

    def search_with_scores(
        self,
        question: str,
        k: int = 2,
        *args,
        score_threshold: Optional[float] = None,
        query_vector: Optional[List[float]] = None,
        **kwargs,
    ) -> List[Tuple[Document, float]]:
        """Search, pairing each hit with its cosine similarity.

        Args:
            query_vector: Precomputed embedding of ``question``; when given the
                store skips embedding the query itself.
        """
        if query_vector is None:
            query_vector = self._embeddings.embed_query(question)
        hits = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            query_filter=self._filter,
            limit=k,
            with_payload=True,
            score_threshold=score_threshold,
        ).points
        return [(self._to_document(hit.payload), hit.score) for hit in hits]

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[dict]] = None,
        *args,
        **kwargs,
    ) -> List[str]:
        """Embed and upsert ``texts``, stamping each with the source id."""
        texts = list(texts)
        if not texts:
            return []
        metadatas = list(metadatas or [{} for _ in texts])
        vectors = self._embeddings.embed_documents(texts)

        points, ids = [], []
        for text, metadata, vector in zip(texts, metadatas, vectors):
            point_id = str(uuid.uuid4())
            payload_metadata = dict(metadata or {})
            payload_metadata["source_id"] = self._source_id
            ids.append(point_id)
            points.append(
                self._models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={"page_content": text, "metadata": payload_metadata},
                )
            )
        self._client.upsert(collection_name=self._collection, points=points)
        return ids

    def save_local(self, *args, **kwargs):
        """No-op: Qdrant persists server-side."""
        pass

    def delete_index(self, *args, **kwargs):
        """Delete every point belonging to this source."""
        return self._client.delete(
            collection_name=self._collection,
            points_selector=self._models.FilterSelector(filter=self._filter),
        )

    def get_chunks(self) -> List[Dict[str, Any]]:
        """Return every chunk stored for this source."""
        chunks: List[Dict[str, Any]] = []
        offset = None
        try:
            while True:
                records, offset = self._client.scroll(
                    collection_name=self._collection,
                    scroll_filter=self._filter,
                    limit=100,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for record in records:
                    payload = record.payload or {}
                    chunks.append(
                        {
                            "doc_id": str(record.id),
                            "text": payload.get("page_content"),
                            "metadata": payload.get("metadata") or {},
                        }
                    )
                if offset is None:
                    break
            return chunks
        except Exception as e:
            logging.error("Error getting chunks: %s", e, exc_info=True)
            return []

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add one chunk and return its id."""
        ids = self.add_texts([text], [metadata or {}])
        return ids[0]

    def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a single chunk by id."""
        try:
            self._client.delete(
                collection_name=self._collection,
                points_selector=self._models.PointIdsList(points=[chunk_id]),
            )
            return True
        except Exception as e:
            logging.error("Error deleting chunk: %s", e, exc_info=True)
            return False
