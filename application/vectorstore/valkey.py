"""Valkey vector store implementation using valkey-glide-sync and valkey-search module."""

import json
import logging
import struct
import uuid
from typing import Any, Dict, List, Optional

try:
    from glide_sync import (
        DataType,
        DistanceMetricType,
        Field,
        FtCreateOptions,
        FtSearchLimit,
        FtSearchOptions,
        GlideClient,
        GlideClientConfiguration,
        NodeAddress,
        ReturnField,
        ServerCredentials,
        TagField,
        TextField,
        VectorAlgorithm,
        VectorField,
        VectorFieldAttributesFlat,
        VectorFieldAttributesHnsw,
        VectorType,
        ft,
    )
except ImportError:
    raise ImportError(
        "Could not import valkey-glide-sync. "
        "Please install with `pip install valkey-glide-sync`."
    )

from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document

logger = logging.getLogger(__name__)

# Characters that must be escaped in Valkey tag field query values.
_TAG_SPECIAL_CHARS = set(r".,<>{}[]\"':;!@#$%^&*()-+=~ /|")

# Batch size for DELETE operations in delete_index.
_DELETE_BATCH_SIZE = 100

# Page size for paginated scan in delete_index / get_chunks.
_SCAN_PAGE_SIZE = 10000


class ValkeyStore(BaseVectorStore):
    """Vector store backed by Valkey with the valkey-search module.

    Uses HASH keys to store document text, metadata, and embedding vectors.
    Creates a search index with FT.CREATE for KNN vector similarity search.

    Requires a Valkey server with the valkey-search module loaded.
    """

    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
    ):
        """Initialize ValkeyStore.

        Args:
            source_id: Identifier for the document source, used to
                namespace and filter documents.
            embeddings_key: Key name or API key for the embeddings provider.
        """
        super().__init__()
        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self._index_name = settings.VALKEY_INDEX_NAME
        self._prefix = settings.VALKEY_PREFIX

        self._client = self._create_client()
        self._ensure_index_exists()

    def close(self):
        """Close the underlying Valkey client connection.

        Should be called when the store is no longer needed to release
        the TCP connection held by the GLIDE client.
        """
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.debug(f"Error closing Valkey client: {e}")
            self._client = None

    def __del__(self):
        """Best-effort cleanup on garbage collection."""
        self.close()

    def _create_client(self) -> GlideClient:
        """Create and return a synchronous Valkey GLIDE client.

        Returns:
            A connected GlideClient instance (synchronous).
        """
        addresses = [NodeAddress(host=settings.VALKEY_HOST, port=settings.VALKEY_PORT)]

        if settings.VALKEY_PASSWORD is not None and settings.VALKEY_PASSWORD != "":
            config = GlideClientConfiguration(
                addresses=addresses,
                use_tls=settings.VALKEY_USE_TLS,
                credentials=ServerCredentials(password=settings.VALKEY_PASSWORD),
                request_timeout=5000,
            )
        else:
            config = GlideClientConfiguration(
                addresses=addresses,
                use_tls=settings.VALKEY_USE_TLS,
                request_timeout=5000,
            )

        return GlideClient.create(config)

    def _ensure_index_exists(self):
        """Create the search index if it does not already exist.

        Uses VALKEY_DISTANCE_METRIC, VALKEY_VECTOR_TYPE, and VALKEY_VECTOR_ALGORITHM
        from settings. Falls back to cosine/float32/hnsw if values are unrecognized.
        """
        embedding_dim = getattr(self._embedding, "dimension", 768)

        distance_metric = self._resolve_distance_metric(settings.VALKEY_DISTANCE_METRIC)
        vector_type = self._resolve_vector_type(settings.VALKEY_VECTOR_TYPE)
        algorithm = self._resolve_vector_algorithm(settings.VALKEY_VECTOR_ALGORITHM)

        logger.info(
            f"Valkey index config: algorithm={algorithm.name}, "
            f"distance_metric={distance_metric.name}, vector_type={vector_type.name}, "
            f"dimensions={embedding_dim}"
        )

        if algorithm == VectorAlgorithm.HNSW:
            vector_field = VectorField(
                name="embedding",
                algorithm=VectorAlgorithm.HNSW,
                attributes=VectorFieldAttributesHnsw(
                    dimensions=embedding_dim,
                    distance_metric=distance_metric,
                    type=vector_type,
                ),
            )
        else:
            vector_field = VectorField(
                name="embedding",
                algorithm=VectorAlgorithm.FLAT,
                attributes=VectorFieldAttributesFlat(
                    dimensions=embedding_dim,
                    distance_metric=distance_metric,
                    type=vector_type,
                ),
            )

        schema: List[Field] = [
            TextField("content"),
            TagField("source_id"),
            vector_field,
        ]

        options = FtCreateOptions(data_type=DataType.HASH, prefixes=[self._prefix])

        try:
            ft.create(self._client, self._index_name, schema, options)
            logger.info(f"Created Valkey search index '{self._index_name}'")
        except Exception as e:
            error_msg = str(e).lower()
            if "already exists" in error_msg or "index already" in error_msg:
                logger.debug(f"Valkey index '{self._index_name}' already exists")
            else:
                logger.error(f"Error creating Valkey index: {e}")
                raise

    @staticmethod
    def _resolve_distance_metric(value: str) -> DistanceMetricType:
        """Resolve distance metric string to enum, defaulting to COSINE.

        Args:
            value: One of "cosine", "l2", or "ip".

        Returns:
            The corresponding DistanceMetricType enum value.
        """
        mapping = {
            "cosine": DistanceMetricType.COSINE,
            "l2": DistanceMetricType.L2,
            "ip": DistanceMetricType.IP,
        }
        result = mapping.get(value.lower().strip())
        if result is None:
            logger.warning(
                f"Unrecognized VALKEY_DISTANCE_METRIC='{value}', "
                f"falling back to 'cosine'. Valid options: cosine, l2, ip"
            )
            return DistanceMetricType.COSINE
        return result

    @staticmethod
    def _resolve_vector_type(value: str) -> VectorType:
        """Resolve vector type string to enum, defaulting to FLOAT32.

        Args:
            value: Currently only "float32" is supported by valkey-glide-sync.

        Returns:
            The corresponding VectorType enum value.
        """
        mapping = {
            "float32": VectorType.FLOAT32,
        }
        result = mapping.get(value.lower().strip())
        if result is None:
            logger.warning(
                f"Unrecognized VALKEY_VECTOR_TYPE='{value}', "
                f"falling back to 'float32'. Valid options: float32"
            )
            return VectorType.FLOAT32
        return result

    @staticmethod
    def _resolve_vector_algorithm(value: str) -> VectorAlgorithm:
        """Resolve vector algorithm string to enum, defaulting to HNSW.

        Args:
            value: One of "hnsw" or "flat".

        Returns:
            The corresponding VectorAlgorithm enum value.
        """
        mapping = {
            "hnsw": VectorAlgorithm.HNSW,
            "flat": VectorAlgorithm.FLAT,
        }
        result = mapping.get(value.lower().strip())
        if result is None:
            logger.warning(
                f"Unrecognized VALKEY_VECTOR_ALGORITHM='{value}', "
                f"falling back to 'hnsw'. Valid options: hnsw, flat"
            )
            return VectorAlgorithm.HNSW
        return result

    @staticmethod
    def _escape_tag_value(value: str) -> str:
        """Escape special characters for Valkey tag field queries.

        Args:
            value: The raw tag value to escape.

        Returns:
            The escaped string safe for use in @field:{...} queries.
        """
        escaped = []
        for ch in value:
            if ch in _TAG_SPECIAL_CHARS:
                escaped.append(f"\\{ch}")
            else:
                escaped.append(ch)
        return "".join(escaped)

    def _doc_key(self, doc_id: str) -> str:
        """Generate a hash key for a document.

        Args:
            doc_id: The unique document identifier.

        Returns:
            The full key including the prefix.
        """
        return f"{self._prefix}{doc_id}"

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        """Search for similar documents using vector similarity.

        Args:
            question: The query text to search for.
            k: Number of results to return.

        Returns:
            A list of Document objects sorted by similarity.
        """
        query_vector = self._embedding.embed_query(question)
        vector_bytes = struct.pack(f"{len(query_vector)}f", *query_vector)

        escaped_source = self._escape_tag_value(self._source_id)
        query = f"@source_id:{{{escaped_source}}} =>[KNN {k} @embedding $BLOB AS score]"

        try:
            results = ft.search(
                self._client,
                self._index_name,
                query,
                FtSearchOptions(
                    params={"BLOB": vector_bytes},
                    return_fields=[
                        ReturnField("content"),
                        ReturnField("source_id"),
                        ReturnField("metadata"),
                    ],
                ),
            )

            return self._parse_search_results(results)

        except Exception as e:
            logger.error(f"Error searching Valkey: {e}", exc_info=True)
            return []

    def _parse_search_results(self, results: list) -> List[Document]:
        """Parse ft.search response into Document objects.

        The response format is: [total_count, {key: {field: value}}, ...]

        Args:
            results: Raw response from ft.search.

        Returns:
            List of Document objects.
        """
        documents = []
        if not results or len(results) < 2:
            return documents

        # results[0] is the total count, results[1:] are mappings of {key: {fields}}
        for entry in results[1:]:
            if isinstance(entry, dict):
                for _key, fields in entry.items():
                    field_dict = self._decode_fields(fields)
                    content = field_dict.get("content", "")
                    metadata = self._parse_metadata(field_dict)
                    documents.append(Document(page_content=content, metadata=metadata))

        return documents

    def _decode_fields(self, fields) -> Dict[str, Any]:
        """Decode bytes in field dict to strings, skipping binary fields.

        Args:
            fields: Dict with potentially bytes keys/values.

        Returns:
            A dictionary with string keys and values (binary fields excluded).
        """
        result = {}
        if isinstance(fields, dict):
            for k, v in fields.items():
                key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                # Skip binary fields (like embedding vectors) that can't be decoded
                if isinstance(v, bytes):
                    try:
                        value = v.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                else:
                    value = str(v) if not isinstance(v, str) else v
                result[key] = value
        return result

    def _parse_metadata(self, field_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metadata from field dictionary.

        Args:
            field_dict: Parsed fields from a document hash.

        Returns:
            Metadata dictionary.
        """
        metadata_str = field_dict.get("metadata", "{}")
        try:
            return json.loads(metadata_str)
        except (json.JSONDecodeError, TypeError):
            return {}

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        *args,
        **kwargs,
    ) -> List[str]:
        """Add texts with embeddings to the vector store.

        Args:
            texts: List of text strings to add.
            metadatas: Optional list of metadata dicts for each text.

        Returns:
            List of document IDs that were added.

        Raises:
            Exception: If any write fails. Successfully written documents
                prior to the failure are not rolled back.
        """
        if not texts:
            return []

        embeddings = self._embedding.embed_documents(texts)
        metadatas = metadatas or [{}] * len(texts)
        doc_ids: List[str] = []

        for text, embedding, metadata in zip(texts, embeddings, metadatas):
            doc_id = str(uuid.uuid4())
            key = self._doc_key(doc_id)
            vector_bytes = struct.pack(f"{len(embedding)}f", *embedding)

            fields = {
                "content": text,
                "source_id": self._source_id,
                "metadata": json.dumps(metadata),
                "embedding": vector_bytes,
            }

            try:
                self._client.hset(key, fields)
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(
                    f"Error adding document to Valkey (wrote {len(doc_ids)}/{len(texts)} "
                    f"before failure): {e}"
                )
                raise

        return doc_ids

    def _paginated_source_scan(self) -> List[str]:
        """Scan all keys matching this source_id, handling pagination.

        Uses a minimal return field to avoid fetching full document content —
        only the key names are needed for deletion.

        Returns:
            List of key strings for all documents with this source_id.
        """
        all_keys: List[str] = []
        offset = 0
        escaped_source = self._escape_tag_value(self._source_id)
        query = f"@source_id:{{{escaped_source}}}"

        while True:
            results = ft.search(
                self._client,
                self._index_name,
                query,
                FtSearchOptions(
                    limit=FtSearchLimit(offset, _SCAN_PAGE_SIZE),
                    return_fields=[ReturnField("source_id")],
                ),
            )

            if not results or len(results) < 2:
                break

            page_keys: List[str] = []
            for entry in results[1:]:
                if isinstance(entry, dict):
                    for key in entry.keys():
                        key_str = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                        page_keys.append(key_str)

            all_keys.extend(page_keys)

            # If we got fewer results than page size, we've reached the end
            if len(page_keys) < _SCAN_PAGE_SIZE:
                break
            offset += _SCAN_PAGE_SIZE

        return all_keys

    def delete_index(self, *args, **kwargs):
        """Delete all documents for this source_id.

        Searches for all documents with matching source_id and deletes them
        in batches. Handles sources with more than 10,000 documents via pagination.
        """
        try:
            keys = self._paginated_source_scan()

            # Batch deletes for efficiency
            for i in range(0, len(keys), _DELETE_BATCH_SIZE):
                batch = keys[i : i + _DELETE_BATCH_SIZE]
                self._client.delete(batch)

        except Exception as e:
            logger.error(f"Error deleting index from Valkey: {e}", exc_info=True)

    def save_local(self, *args, **kwargs):
        """No-op for Valkey — data is already persisted."""
        pass

    def get_chunks(self) -> List[Dict[str, Any]]:
        """Get all chunks for this source_id.

        Returns:
            List of chunk dicts with doc_id, text, and metadata.
        """
        try:
            escaped_source = self._escape_tag_value(self._source_id)
            query = f"@source_id:{{{escaped_source}}}"

            chunks: List[Dict[str, Any]] = []
            offset = 0

            while True:
                results = ft.search(
                    self._client,
                    self._index_name,
                    query,
                    FtSearchOptions(
                        limit=FtSearchLimit(offset, _SCAN_PAGE_SIZE),
                        return_fields=[
                            ReturnField("content"),
                            ReturnField("source_id"),
                            ReturnField("metadata"),
                        ],
                    ),
                )

                if not results or len(results) < 2:
                    break

                page_count = 0
                for entry in results[1:]:
                    if isinstance(entry, dict):
                        for key, fields in entry.items():
                            key_str = (
                                key.decode("utf-8") if isinstance(key, bytes) else str(key)
                            )
                            doc_id = key_str.replace(self._prefix, "", 1)
                            field_dict = self._decode_fields(fields)
                            chunks.append(
                                {
                                    "doc_id": doc_id,
                                    "text": field_dict.get("content", ""),
                                    "metadata": self._parse_metadata(field_dict),
                                }
                            )
                            page_count += 1

                if page_count < _SCAN_PAGE_SIZE:
                    break
                offset += _SCAN_PAGE_SIZE

            return chunks

        except Exception as e:
            logger.error(f"Error getting chunks from Valkey: {e}", exc_info=True)
            return []

    def add_chunk(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add a single chunk to the vector store.

        Args:
            text: The text content of the chunk.
            metadata: Optional metadata dictionary.

        Returns:
            The generated document ID.
        """
        metadata = metadata or {}
        final_metadata = metadata.copy()
        final_metadata["source_id"] = self._source_id

        embeddings = self._embedding.embed_documents([text])
        if not embeddings:
            raise ValueError("Could not generate embedding for chunk")

        doc_id = str(uuid.uuid4())
        key = self._doc_key(doc_id)
        vector_bytes = struct.pack(f"{len(embeddings[0])}f", *embeddings[0])

        fields = {
            "content": text,
            "source_id": self._source_id,
            "metadata": json.dumps(final_metadata),
            "embedding": vector_bytes,
        }

        try:
            self._client.hset(key, fields)
            return doc_id
        except Exception as e:
            logger.error(f"Error adding chunk to Valkey: {e}")
            raise

    def delete_chunk(self, chunk_id: str) -> bool:
        """Delete a specific chunk by its ID.

        Args:
            chunk_id: The document ID to delete.

        Returns:
            True if the chunk was deleted, False otherwise.
        """
        try:
            key = self._doc_key(chunk_id)
            result = self._client.delete([key])
            return result > 0
        except Exception as e:
            logger.error(f"Error deleting chunk from Valkey: {e}", exc_info=True)
            return False
