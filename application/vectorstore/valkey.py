"""Valkey vector store implementation using valkey-glide-sync and valkey-search module.

NOTE: The try/except ImportError guard around the glide_sync import below is
**required** by ``application/vectorstore/vector_creator.py`` which eagerly
imports all vector store modules at module level.  Without this guard, a missing
``valkey-glide-sync`` package would break VectorCreator for *all* backends.
"""

import json
import logging
import struct
import uuid
from typing import Any, Dict, Generator, List, Optional, Tuple

_GLIDE_AVAILABLE = False
try:
    from glide_sync import (
        Batch,
        ConnectionError as GlideConnectionError,
        DataType,
        DistanceMetricType,
        Field,
        FtCreateOptions,
        FtSearchLimit,
        FtSearchOptions,
        GlideClient,
        GlideClientConfiguration,
        NodeAddress,
        RequestError,
        ReturnField,
        ServerCredentials,
        TagField,
        TextField,
        TimeoutError as GlideTimeoutError,
        VectorAlgorithm,
        VectorField,
        VectorFieldAttributesFlat,
        VectorFieldAttributesHnsw,
        VectorType,
        ft,
    )

    _GLIDE_AVAILABLE = True
except ImportError:
    pass

from application.core.settings import settings  # noqa: E402
from application.vectorstore.base import BaseVectorStore  # noqa: E402
from application.vectorstore.document_class import Document  # noqa: E402

logger = logging.getLogger(__name__)

# Characters that must be escaped in Valkey tag field query values.
# Includes '?' which is a single-character wildcard in valkey-search TAG queries.
_TAG_SPECIAL_CHARS = set(r".,<>{}[]\"':;!@#$%^&*()-+=~ /|?")

# Batch size for DELETE operations in delete_index.
_DELETE_BATCH_SIZE = 100

# Page size for paginated scan in delete_index / get_chunks.
_SCAN_PAGE_SIZE = 10000

# Safety limit to prevent infinite pagination loops (supports ~10M documents).
_MAX_SCAN_PAGES = 1000

# Maximum allowed k for vector search to prevent memory exhaustion.
_MAX_SEARCH_K = 100


class ValkeyStore(BaseVectorStore):
    """Vector store backed by Valkey with the valkey-search module.

    Uses HASH keys to store document text, metadata, and embedding vectors.
    Creates a search index with FT.CREATE for KNN vector similarity search.

    Requires a Valkey server with the valkey-search module loaded.

    Supports use as a context manager for deterministic connection cleanup::

        with ValkeyStore(source_id="my-source") as store:
            store.search("query")
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

        Raises:
            ImportError: If valkey-glide-sync is not installed.
        """
        if not _GLIDE_AVAILABLE:
            raise ImportError(
                "Could not import valkey-glide-sync. "
                "Please install with `pip install valkey-glide-sync`."
            )
        super().__init__()
        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self._index_name = settings.VALKEY_INDEX_NAME
        self._prefix = settings.VALKEY_PREFIX

        self._client = self._create_client()
        self._ensure_index_exists()

    # --- Context manager support ---

    def __enter__(self):
        """Enter the context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager and close the connection."""
        self.close()
        return False

    # --- Connection lifecycle ---

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
        timeout = settings.VALKEY_REQUEST_TIMEOUT

        if settings.VALKEY_PASSWORD is not None and settings.VALKEY_PASSWORD != "":
            config = GlideClientConfiguration(
                addresses=addresses,
                use_tls=settings.VALKEY_USE_TLS,
                credentials=ServerCredentials(password=settings.VALKEY_PASSWORD),
                request_timeout=timeout,
            )
        else:
            config = GlideClientConfiguration(
                addresses=addresses,
                use_tls=settings.VALKEY_USE_TLS,
                request_timeout=timeout,
            )

        return GlideClient.create(config)

    def _ensure_index_exists(self):
        """Create the search index if it does not already exist.

        Uses VALKEY_DISTANCE_METRIC, VALKEY_VECTOR_TYPE, and VALKEY_VECTOR_ALGORITHM
        from settings. Falls back to cosine/float32/hnsw if values are unrecognized.
        """
        embedding_dim = getattr(self._embedding, "dimension", None)
        if embedding_dim is None:
            probe = self._embedding.embed_query("dimension probe")
            embedding_dim = len(probe)

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
        except RequestError as e:
            error_msg = str(e).lower()
            if "already exists" in error_msg or "index already" in error_msg:
                logger.debug(f"Valkey index '{self._index_name}' already exists")
            else:
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

    # --- Shared pagination helper ---

    def _paginated_search(
        self, query: str, return_fields: List[ReturnField]
    ) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        """Yield (key_str, field_dict) tuples across all pages.

        Handles pagination with a safety limit of _MAX_SCAN_PAGES iterations
        to prevent infinite loops from concurrent inserts.

        Args:
            query: The ft.search query string.
            return_fields: Fields to return from each document.

        Yields:
            Tuples of (key_string, field_dictionary) for each matched document.
        """
        offset = 0
        for _ in range(_MAX_SCAN_PAGES):
            results = ft.search(
                self._client,
                self._index_name,
                query,
                FtSearchOptions(
                    limit=FtSearchLimit(offset, _SCAN_PAGE_SIZE),
                    return_fields=return_fields,
                ),
            )

            if not results or len(results) < 2:
                break

            page_count = 0
            for entry in results[1:]:
                if isinstance(entry, dict):
                    for key, fields in entry.items():
                        key_str = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                        yield key_str, fields
                        page_count += 1

            if page_count < _SCAN_PAGE_SIZE:
                break
            offset += _SCAN_PAGE_SIZE

    # --- Public interface ---

    def search(self, question: str, k: int = 2, *args, **kwargs) -> List[Document]:
        """Search for similar documents using vector similarity.

        Args:
            question: The query text to search for.
            k: Number of results to return (capped at 100).

        Returns:
            A list of Document objects sorted by similarity.
        """
        k = max(1, min(k, _MAX_SEARCH_K))
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

        except (RequestError, GlideConnectionError, GlideTimeoutError) as e:
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

        # Use non-atomic Batch (pipeline) to reduce network round trips.
        batch = Batch(False)
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

            batch.hset(key, fields)
            doc_ids.append(doc_id)

        try:
            self._client.exec(batch, raise_on_error=True)
        except (RequestError, GlideConnectionError, GlideTimeoutError) as e:
            logger.error(
                f"Error adding documents to Valkey via pipeline "
                f"({len(doc_ids)} documents): {e}"
            )
            raise

        return doc_ids

    def delete_index(self, *args, **kwargs):
        """Delete all documents for this source_id.

        Searches for all documents with matching source_id and deletes them
        in batches. Handles sources with more than 10,000 documents via pagination.

        Raises:
            RequestError: If the Valkey server returns an error.
            ConnectionError: If the connection to Valkey is lost.
            TimeoutError: If the operation exceeds the request timeout.
        """
        escaped_source = self._escape_tag_value(self._source_id)
        query = f"@source_id:{{{escaped_source}}}"

        keys = [
            key_str
            for key_str, _ in self._paginated_search(query, [ReturnField("source_id")])
        ]

        # Batch deletes for efficiency
        for i in range(0, len(keys), _DELETE_BATCH_SIZE):
            batch = keys[i : i + _DELETE_BATCH_SIZE]
            self._client.delete(batch)

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

            for key_str, fields in self._paginated_search(
                query,
                [
                    ReturnField("content"),
                    ReturnField("source_id"),
                    ReturnField("metadata"),
                ],
            ):
                doc_id = key_str.replace(self._prefix, "", 1)
                field_dict = self._decode_fields(fields)
                chunks.append(
                    {
                        "doc_id": doc_id,
                        "text": field_dict.get("content", ""),
                        "metadata": self._parse_metadata(field_dict),
                    }
                )

            return chunks

        except (RequestError, GlideConnectionError, GlideTimeoutError) as e:
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
        except (RequestError, GlideConnectionError, GlideTimeoutError) as e:
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
        except (RequestError, GlideConnectionError, GlideTimeoutError) as e:
            logger.error(f"Error deleting chunk from Valkey: {e}", exc_info=True)
            return False
