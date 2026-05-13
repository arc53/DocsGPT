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
        ServerCredentials,
        TagField,
        TextField,
        VectorAlgorithm,
        VectorField,
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

    def _create_client(self) -> GlideClient:
        """Create and return a synchronous Valkey GLIDE client.

        Returns:
            A connected GlideClient instance (synchronous).
        """
        addresses = [NodeAddress(host=settings.VALKEY_HOST, port=settings.VALKEY_PORT)]

        if settings.VALKEY_PASSWORD:
            config = GlideClientConfiguration(
                addresses=addresses,
                use_tls=settings.VALKEY_USE_TLS,
                credentials=ServerCredentials(password=settings.VALKEY_PASSWORD),
            )
        else:
            config = GlideClientConfiguration(
                addresses=addresses,
                use_tls=settings.VALKEY_USE_TLS,
            )

        return GlideClient.create(config)

    def _ensure_index_exists(self):
        """Create the search index if it does not already exist."""
        embedding_dim = getattr(self._embedding, "dimension", 768)

        schema: List[Field] = [
            TextField("content"),
            TagField("source_id"),
            VectorField(
                name="embedding",
                algorithm=VectorAlgorithm.HNSW,
                attributes=VectorFieldAttributesHnsw(
                    dimensions=embedding_dim,
                    distance_metric=DistanceMetricType.COSINE,
                    type=VectorType.FLOAT32,
                ),
            ),
        ]

        options = FtCreateOptions(data_type=DataType.HASH, prefixes=[self._prefix])

        try:
            ft.create(self._client, self._index_name, schema, options)
            logger.info(f"Created Valkey search index '{self._index_name}'")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug(f"Valkey index '{self._index_name}' already exists")
            else:
                logger.error(f"Error creating Valkey index: {e}")
                raise

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

        # KNN search with source_id filter
        query = f"@source_id:{{{self._source_id}}} =>[KNN {k} @embedding $BLOB AS score]"

        try:
            results = ft.search(
                self._client,
                self._index_name,
                query,
                FtSearchOptions(params={"BLOB": vector_bytes}),
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
        """
        if not texts:
            return []

        embeddings = self._embedding.embed_documents(texts)
        metadatas = metadatas or [{}] * len(texts)
        doc_ids = []

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
                logger.error(f"Error adding document to Valkey: {e}")
                raise

        return doc_ids

    def delete_index(self, *args, **kwargs):
        """Delete all documents for this source_id.

        Searches for all documents with matching source_id and deletes them.
        """
        try:
            query = f"@source_id:{{{self._source_id}}}"
            results = ft.search(
                self._client,
                self._index_name,
                query,
                FtSearchOptions(limit=FtSearchLimit(0, 10000)),
            )

            if results and len(results) > 1:
                for entry in results[1:]:
                    if isinstance(entry, dict):
                        for key in entry.keys():
                            key_str = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                            self._client.delete([key_str])

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
            query = f"@source_id:{{{self._source_id}}}"
            results = ft.search(
                self._client,
                self._index_name,
                query,
                FtSearchOptions(limit=FtSearchLimit(0, 10000)),
            )

            chunks = []
            if results and len(results) > 1:
                for entry in results[1:]:
                    if isinstance(entry, dict):
                        for key, fields in entry.items():
                            key_str = key.decode("utf-8") if isinstance(key, bytes) else str(key)
                            doc_id = key_str.replace(self._prefix, "", 1)
                            field_dict = self._decode_fields(fields)
                            chunks.append({
                                "doc_id": doc_id,
                                "text": field_dict.get("content", ""),
                                "metadata": self._parse_metadata(field_dict),
                            })

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
