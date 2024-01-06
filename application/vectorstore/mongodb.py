from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
from application.vectorstore.document_class import Document

class MongoDBVectorStore(BaseVectorStore):
    def __init__(
        self,
        path: str = "",
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
        self._path = path.replace("application/indexes/", "").rstrip("/")
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
                    "filter": {
                        "store": {"$eq": self._path}
                    }
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
        # insert the documents in MongoDB Atlas
        insert_result = self._collection.insert_many(to_insert)
        return insert_result.inserted_ids
    
    def add_texts(self,
        texts,
        metadatas = None,
        ids = None,
        refresh_indices = True,
        create_index_if_not_exists = True,
        bulk_kwargs = None,
        **kwargs,):


        #dims = self._embedding.client[1].word_embedding_dimension
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
        self._collection.delete_many({"store": self._path})