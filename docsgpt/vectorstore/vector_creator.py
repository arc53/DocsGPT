from docsgpt.vectorstore.faiss import FaissStore
from docsgpt.vectorstore.elasticsearch import ElasticsearchStore
from docsgpt.vectorstore.milvus import MilvusStore
from docsgpt.vectorstore.mongodb import MongoDBVectorStore
from docsgpt.vectorstore.qdrant import QdrantStore
from docsgpt.vectorstore.pgvector import PGVectorStore


class VectorCreator:
    vectorstores = {
        "faiss": FaissStore,
        "elasticsearch": ElasticsearchStore,
        "mongodb": MongoDBVectorStore,
        "qdrant": QdrantStore,
        "milvus": MilvusStore,
        "pgvector": PGVectorStore
    }

    @classmethod
    def create_vectorstore(cls, type, *args, **kwargs):
        vectorstore_class = cls.vectorstores.get(type.lower())
        if not vectorstore_class:
            raise ValueError(f"No vectorstore class found for type {type}")
        return vectorstore_class(*args, **kwargs)
