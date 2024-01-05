from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
from application.vectorstore.document_class import Document

class MongoDBVectorStore(BaseVectorStore):
    def __init__(
        self,
        collection: str = "documents",
        index_name: str = "default",
        text_key: str = "text",
        embedding_key: str = "embedding",
        embedding_api_key: str = "embedding_api_key",
        path: str = "",
    ):
        self._collection = collection
        self._embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, embedding_api_key)
        self._index_name = index_name
        self._text_key = text_key
        self._embedding_key = embedding_key
        self._mongo_uri = settings.MONGO_URI
        self._path = path
        # import pymongo
        try:
            import pymongo
        except ImportError:
            raise ImportError(
                "Could not import pymongo python package. "
                "Please install it with `pip install pymongo`."
            )
        self._client = pymongo.MongoClient(self._mongo_uri)
        
    def search(self, question, k=2, *args, **kwargs):
        query_vector = self._embeddings.embed_query(question)
        
        pipeline = [
            {
                "$vectorSearch": {
                    "queryVector": query_vector, 
                    "path": self._embedding_key,
                    "limit": k, 
                    "index": self._index_name
                }
            }
        ]
        
        cursor = self._client._collection.aggregate(pipeline)
        
        results = []
        for doc in cursor:
            text = doc[self._text_key]
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
        insert_result = self.client._collection.insert_many(to_insert)
        return insert_result.inserted_ids
    
    def add_texts(self,
        texts,
        metadatas = None,
        ids = None,
        refresh_indices = True,
        create_index_if_not_exists = True,
        bulk_kwargs = None,
        **kwargs,):


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