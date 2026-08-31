import logging
import os
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document


@contextmanager
def _without_milvus_uri_env():
    """Hide ``MILVUS_URI`` from pymilvus while it is imported.

    pymilvus reads the ``MILVUS_URI`` environment variable at import time and
    rejects anything that is not an ``http[s]://`` URL. DocsGPT's setting of
    the same name defaults to a Milvus Lite file path, and ``load_dotenv``
    puts it on the environment — so an unguarded import raises before the
    store can pass its own ``uri``. The value is restored immediately after.
    """
    sentinel = object()
    previous = os.environ.pop("MILVUS_URI", sentinel)
    try:
        yield
    finally:
        if previous is not sentinel:
            os.environ["MILVUS_URI"] = previous


class MilvusStore(BaseVectorStore):
    """Vector store backed by Milvus through the native ``pymilvus`` client.

    Defaults to Milvus Lite (a local file at ``MILVUS_URI``); point
    ``MILVUS_URI`` at a server URL to use a full deployment. Rows carry an
    indexed ``source_id`` so one collection can hold many sources.
    """

    score_kind = "cosine_similarity"

    def __init__(self, source_id: str = "", embeddings_key: str = "embeddings"):
        super().__init__()
        with _without_milvus_uri_env():
            from pymilvus import DataType, MilvusClient

        self._DataType = DataType
        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        self._collection = settings.MILVUS_COLLECTION_NAME
        self._embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self._client = MilvusClient(
            uri=settings.MILVUS_URI, token=settings.MILVUS_TOKEN or ""
        )
        self._ensure_collection()

    @property
    def _filter(self) -> str:
        """Boolean expression scoping every read to this source."""
        escaped = self._source_id.replace('"', '\\"')
        return f'source_id == "{escaped}"'

    def _dimension(self) -> int:
        """Resolve the embedding width, probing the model when unset."""
        dimension = getattr(self._embeddings, "dimension", None)
        if not dimension:
            dimension = len(self._embeddings.embed_query("dimension probe"))
        return dimension

    def _ensure_collection(self) -> None:
        """Create the collection, its vector index and the source_id index."""
        if self._client.has_collection(self._collection):
            return
        DataType = self._DataType
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self._dimension())
        schema.add_field("text", DataType.VARCHAR, max_length=65535)
        schema.add_field("source_id", DataType.VARCHAR, max_length=512)
        schema.add_field("metadata", DataType.JSON, nullable=True)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="vector", index_type="AUTOINDEX", metric_type="COSINE"
        )
        try:
            self._client.create_collection(
                collection_name=self._collection,
                schema=schema,
                index_params=index_params,
            )
        except Exception as e:
            # A concurrent worker may have created it first.
            if "already exist" not in str(e).lower():
                raise

    @staticmethod
    def _to_document(row: Dict[str, Any]) -> Document:
        row = row or {}
        return Document(
            page_content=row.get("text") or "",
            metadata=row.get("metadata") or {},
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
        results = self._client.search(
            collection_name=self._collection,
            data=[query_vector],
            filter=self._filter,
            limit=k,
            output_fields=["text", "metadata"],
        )
        hits = results[0] if results else []
        out = []
        for hit in hits:
            score = hit.get("distance")
            if score_threshold is not None and score is not None and score < score_threshold:
                continue
            out.append((self._to_document(hit.get("entity") or {}), score))
        return out

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[dict]] = None,
        *args,
        **kwargs,
    ) -> List[str]:
        """Embed and insert ``texts``, stamping each with the source id."""
        texts = list(texts)
        if not texts:
            return []
        metadatas = list(metadatas or [{} for _ in texts])
        vectors = self._embeddings.embed_documents(texts)

        rows, ids = [], []
        for text, metadata, vector in zip(texts, metadatas, vectors):
            row_id = str(uuid.uuid4())
            row_metadata = dict(metadata or {})
            row_metadata["source_id"] = self._source_id
            ids.append(row_id)
            rows.append(
                {
                    "id": row_id,
                    "vector": vector,
                    "text": text,
                    "source_id": self._source_id,
                    "metadata": row_metadata,
                }
            )
        self._client.insert(collection_name=self._collection, data=rows)
        return ids

    def save_local(self, *args, **kwargs):
        """No-op: Milvus persists server-side."""
        pass

    def delete_index(self, *args, **kwargs):
        """Delete every row belonging to this source."""
        try:
            return self._client.delete(
                collection_name=self._collection, filter=self._filter
            )
        except Exception as e:
            logging.error("Error deleting index: %s", e, exc_info=True)
            return None

    def get_chunks(self) -> List[Dict[str, Any]]:
        """Return every chunk stored for this source."""
        try:
            rows = self._client.query(
                collection_name=self._collection,
                filter=self._filter,
                output_fields=["id", "text", "metadata"],
            )
            return [
                {
                    "doc_id": row.get("id"),
                    "text": row.get("text"),
                    "metadata": row.get("metadata") or {},
                }
                for row in rows
            ]
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
            self._client.delete(collection_name=self._collection, ids=[chunk_id])
            return True
        except Exception as e:
            logging.error("Error deleting chunk: %s", e, exc_info=True)
            return False
