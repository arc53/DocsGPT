import logging
from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
from application.vectorstore.document_class import Document


class QdrantStore(BaseVectorStore):
    def __init__(self, source_id: str = "", embeddings_key: str = "embeddings"):
        from qdrant_client import models
        from langchain_community.vectorstores.qdrant import Qdrant

        # Store the source_id for use in add_chunk
        self._source_id = str(source_id).replace("application/indexes/", "").rstrip("/")
        
        self._filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.source_id",
                    match=models.MatchValue(value=self._source_id),
                )
            ]
        )

        embedding=self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)
        self._docsearch = Qdrant.construct_instance(
            ["TEXT_TO_OBTAIN_EMBEDDINGS_DIMENSION"],
            embedding=embedding,
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
        try:
            collections = self._docsearch.client.get_collections()
            collection_exists = settings.QDRANT_COLLECTION_NAME in [
                collection.name for collection in collections.collections
            ]
            
            if not collection_exists:
                self._docsearch.client.recreate_collection(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    vectors_config=models.VectorParams(size=embedding.client[1].word_embedding_dimension, distance=models.Distance.COSINE),
                )
            
            # Ensure the required index exists for metadata.source_id
            try:
                self._docsearch.client.create_payload_index(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    field_name="metadata.source_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception as index_error:
                # Index might already exist, which is fine
                if "already exists" not in str(index_error).lower():
                    logging.warning(f"Could not create index for metadata.source_id: {index_error}")
                    
        except Exception as e:
            logging.warning(f"Could not check for collection: {e}")

    def search(self, *args, **kwargs):
        return self._docsearch.similarity_search(filter=self._filter, *args, **kwargs)

    def add_texts(self, *args, **kwargs):
        return self._docsearch.add_texts(*args, **kwargs)

    def save_local(self, *args, **kwargs):
        pass

    def delete_index(self, *args, **kwargs):
        return self._docsearch.client.delete(
            collection_name=settings.QDRANT_COLLECTION_NAME, points_selector=self._filter
        )

    def get_chunks(self):
        try:

            chunks = []
            offset = None
            while True:
                records, offset = self._docsearch.client.scroll(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    scroll_filter=self._filter,
                    limit=10,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for record in records:
                    doc_id = record.id
                    text = record.payload.get("page_content")
                    metadata = record.payload.get("metadata")
                    chunks.append(
                        {"doc_id": doc_id, "text": text, "metadata": metadata}
                    )
                if offset is None:
                    break
            return chunks
        except Exception as e:
            logging.error(f"Error getting chunks: {e}", exc_info=True)
            return []

    def add_chunk(self, text, metadata=None):
        import uuid
        metadata = metadata or {}
        
        # Create a copy to avoid modifying the original metadata
        final_metadata = metadata.copy()
        
        # Ensure the source_id is in the metadata so the chunk can be found by filters
        final_metadata["source_id"] = self._source_id
        
        doc = Document(page_content=text, metadata=final_metadata)
        # Generate a unique ID for the document
        doc_id = str(uuid.uuid4())
        doc.id = doc_id
        doc_ids = self._docsearch.add_documents([doc])
        return doc_ids[0] if doc_ids else doc_id

    def delete_chunk(self, chunk_id):
        try:
            self._docsearch.client.delete(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                points_selector=[chunk_id],
            )
            return True
        except Exception as e:
            logging.error(f"Error deleting chunk: {e}", exc_info=True)
            return False
