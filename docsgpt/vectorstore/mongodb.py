import logging
from functools import cached_property

from docsgpt.core.settings import settings
from docsgpt.vectorstore.base import BaseVectorStore, InvalidChunkMetadataError
from docsgpt.vectorstore.document_class import Document


def _lazy_import_pymongo():
    """Lazy import of pymongo so installations that don't use the MongoDB vectorstore don't need it."""
    try:
        import pymongo
    except ImportError as exc:
        raise ImportError(
            "Could not import pymongo python package. "
            "Please install it with `pip install pymongo`."
        ) from exc
    return pymongo


class MongoDBVectorStore(BaseVectorStore):
    def __init__(
        self,
        source_id: str = "",
        embeddings_key: str = "embeddings",
        collection: str = "documents",
        index_name: str = "vector_search_index",
        text_key: str = "text",
        embedding_key: str = "embedding",
        database: str = "docsgpt",
    ):
        self._index_name = index_name
        self._text_key = text_key
        self._embedding_key = embedding_key
        self._embeddings_key = embeddings_key
        self._mongo_uri = settings.MONGO_URI
        self._database_name = database
        self._collection_name = collection
        self._source_id = source_id.replace("docsgpt/indexes/", "").rstrip("/")
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

    @cached_property
    def _client(self):
        pymongo = _lazy_import_pymongo()
        return pymongo.MongoClient(self._mongo_uri)

    @cached_property
    def _database(self):
        return self._client[self._database_name]

    @cached_property
    def _collection(self):
        return self._database[self._collection_name]

    score_kind = "cosine_similarity"

    def search(
        self, question, k=2, *args, score_threshold=None, query_vector=None, **kwargs
    ):
        """Search via Atlas ``$vectorSearch``.

        Args:
            question: The query string.
            k: Maximum number of results.
            score_threshold: Optional ``vectorSearchScore`` floor in ``[0, 1]``;
                results scoring below it are dropped.
            query_vector: Precomputed embedding of ``question``, so a caller
                searching several sources embeds the query only once.
        """
        return [
            doc
            for doc, _ in self.search_with_scores(
                question,
                k,
                *args,
                score_threshold=score_threshold,
                query_vector=query_vector,
                **kwargs,
            )
        ]

    def search_with_scores(
        self, question, k=2, *args, score_threshold=None, query_vector=None, **kwargs
    ):
        """Same search as :meth:`search`, pairing each hit with its score.

        The score is Atlas' ``vectorSearchScore`` — the same quantity
        ``score_threshold`` is compared against. ``query_vector`` skips the
        per-store query embedding when the caller already has one.
        """
        if query_vector is None:
            query_vector = self._embedding.embed_query(question)

        pipeline = [
            {
                "$vectorSearch": {
                    "queryVector": query_vector,
                    "path": self._embedding_key,
                    "limit": k,
                    "numCandidates": k * 10,
                    "index": self._index_name,
                    "filter": {"source_id": {"$eq": self._source_id}},
                }
            },
            {"$addFields": {"_score": {"$meta": "vectorSearchScore"}}},
        ]
        if score_threshold is not None:
            pipeline.append({"$match": {"_score": {"$gte": float(score_threshold)}}})

        cursor = self._collection.aggregate(pipeline)

        results = []
        for doc in cursor:
            text = doc[self._text_key]
            doc.pop("_id")
            doc.pop(self._text_key)
            doc.pop(self._embedding_key)
            score = doc.pop("_score", None)
            metadata = doc
            results.append(
                (Document(text, metadata), None if score is None else float(score))
            )
        return results

    def _insert_texts(self, texts, metadatas):
        if not texts:
            return []
        embeddings = self._embedding.embed_documents(texts)

        to_insert = [
            {self._text_key: t, self._embedding_key: embedding, **m}
            for t, m, embedding in zip(texts, metadatas, embeddings)
        ]

        insert_result = self._collection.insert_many(to_insert)
        return insert_result.inserted_ids

    def add_texts(
        self,
        texts,
        metadatas=None,
        ids=None,
        refresh_indices=True,
        create_index_if_not_exists=True,
        bulk_kwargs=None,
        **kwargs,
    ):

        # dims = self._embedding.client[1].word_embedding_dimension
        # # check if index exists
        # if create_index_if_not_exists:
        #     # check if index exists
        #     info = self._collection.index_information()
        #     if self._index_name not in info:
        #         index_mongo = {
        #         "fields": [{
        #             "type": "vector",
        #             "path": self._embedding_key,
        #             "numDimensions": dims,
        #             "similarity": "cosine",
        #         },
        #         {
        #             "type": "filter",
        #             "path": "store"
        #         }]
        #         }
        #         self._collection.create_index(self._index_name, index_mongo)

        batch_size = 100
        _metadatas = metadatas or ({} for _ in texts)
        texts_batch = []
        metadatas_batch = []
        result_ids = []
        for i, (text, metadata) in enumerate(zip(texts, _metadatas)):
            texts_batch.append(text)
            metadatas_batch.append(metadata)
            if (i + 1) % batch_size == 0:
                result_ids.extend(self._insert_texts(texts_batch, metadatas_batch))
                texts_batch = []
                metadatas_batch = []
        if texts_batch:
            result_ids.extend(self._insert_texts(texts_batch, metadatas_batch))
        return result_ids

    def delete_index(self, *args, **kwargs):
        self._collection.delete_many({"source_id": self._source_id})

    def get_chunks(self):
        try:
            chunks = []
            cursor = self._collection.find({"source_id": self._source_id})
            for doc in cursor:
                doc_id = str(doc.get("_id"))
                text = doc.get(self._text_key)
                metadata = {
                    k: v
                    for k, v in doc.items()
                    if k
                    not in ["_id", self._text_key, self._embedding_key, "source_id"]
                }

                if text:
                    chunks.append(
                        {"doc_id": doc_id, "text": text, "metadata": metadata}
                    )

            return chunks
        except Exception as e:
            logging.error(f"Error getting chunks: {e}", exc_info=True)
            return []

    def add_chunk(self, text, metadata=None):
        metadata = metadata or {}
        embeddings = self._embedding.embed_documents([text])
        if not embeddings:
            raise ValueError("Could not generate embedding for chunk")

        chunk_data = {
            self._text_key: text,
            self._embedding_key: embeddings[0],
            "source_id": self._source_id,
            **metadata,
        }
        result = self._collection.insert_one(chunk_data)
        return str(result.inserted_id)

    def update_chunk(self, chunk_id: str, text: str, metadata: dict) -> str:
        """Rewrite a chunk's document in place, keeping its ``_id``.

        Metadata lives as top-level fields, so the new metadata is ``$set``
        and any field the record carries but the new metadata lacks is
        ``$unset``; the record then holds exactly the new metadata. ``_id``,
        the text, the embedding and ``source_id`` are reserved and cannot be
        overwritten through ``metadata``. The embedding is computed before
        anything is written.

        Args:
            chunk_id: Id of the chunk to replace.
            text: The chunk's new text.
            metadata: The chunk's complete new metadata.

        Returns:
            ``chunk_id``, unchanged.

        Raises:
            KeyError: If this source has no chunk with that id.
            InvalidChunkMetadataError: If a metadata key is empty, contains
                ``.`` or starts with ``$``. Mongo reads those as a path or an
                operator, so ``$set`` would fail or write a nested field.
            ValueError: If no embedding could be generated.
        """
        from bson.objectid import ObjectId

        for key in metadata or {}:
            if not isinstance(key, str) or not key or "." in key or key.startswith("$"):
                raise InvalidChunkMetadataError(
                    f"Metadata key {key!r} is not allowed: keys must be non-empty, "
                    "contain no '.' and not start with '$'"
                )

        query = {"_id": ObjectId(chunk_id), "source_id": self._source_id}
        existing = self._collection.find_one(query)
        if existing is None:
            raise KeyError(f"Chunk {chunk_id} not found for source {self._source_id}")

        embeddings = self._embedding.embed_documents([text])
        if not embeddings:
            raise ValueError("Could not generate embedding for chunk")

        reserved = {"_id", self._text_key, self._embedding_key, "source_id"}
        fields = {k: v for k, v in (metadata or {}).items() if k not in reserved}
        update = {
            "$set": {
                self._text_key: text,
                self._embedding_key: embeddings[0],
                "source_id": self._source_id,
                **fields,
            }
        }
        stale = {k: "" for k in existing if k not in reserved and k not in fields}
        if stale:
            update["$unset"] = stale

        result = self._collection.update_one(query, update)
        if result.matched_count == 0:
            raise KeyError(f"Chunk {chunk_id} not found for source {self._source_id}")
        return chunk_id

    def delete_chunk(self, chunk_id):
        try:
            from bson.objectid import ObjectId

            object_id = ObjectId(chunk_id)
            result = self._collection.delete_one({"_id": object_id})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error deleting chunk: {e}", exc_info=True)
            return False
