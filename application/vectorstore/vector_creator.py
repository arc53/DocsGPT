from application.vectorstore.faiss import FaissStore
from application.vectorstore.elasticsearch import ElasticsearchStore
from application.vectorstore.milvus import MilvusStore
from application.vectorstore.mongodb import MongoDBVectorStore
from application.vectorstore.qdrant import QdrantStore
from application.vectorstore.pgvector import PGVectorStore
from application.vectorstore.oracle import OracleVectorStore


class VectorCreator:
    vectorstores = {
        "faiss": FaissStore,
        "elasticsearch": ElasticsearchStore,
        "mongodb": MongoDBVectorStore,
        "oracle": OracleVectorStore,
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
