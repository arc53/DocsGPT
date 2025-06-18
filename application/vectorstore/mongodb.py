import logging
from application.core.settings import settings
from application.vectorstore.base import BaseVectorStore
from application.vectorstore.document_class import Document


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
        self._source_id = source_id.replace("application/indexes/", "").rstrip("/")
        self._embedding = self._get_embeddings(settings.EMBEDDINGS_NAME, embeddings_key)

        try:
            import pymongo
        except ImportError:
            raise ImportError(
                "Could not import pymongo python package. "
                "Please install it with `pip install pymongo`."
            )

        self._client = pymongo.MongoClient(self._mongo_uri)
        self._database = self._client[database]
        self._collection = self._database[collection]

    def search(self, question, k=2, *args, **kwargs):
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
            }
        ]

        cursor = self._collection.aggregate(pipeline)

        results = []
        for doc in cursor:
            text = doc[self._text_key]
            doc.pop("_id")
            doc.pop(self._text_key)
            doc.pop(self._embedding_key)
            metadata = doc
            results.append(Document(text, metadata))
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

    def delete_chunk(self, chunk_id):
        try:
            from bson.objectid import ObjectId

            object_id = ObjectId(chunk_id)
            result = self._collection.delete_one({"_id": object_id})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error deleting chunk: {e}", exc_info=True)
            return False
