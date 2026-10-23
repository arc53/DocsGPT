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
    def supports_chunk_edits(cls, type: str) -> bool:
        """Whether the store named ``type`` can add, list and delete single chunks.

        Answered from the class, so no store (or FAISS index) is loaded.

        Args:
            type: A ``VECTOR_STORE`` value.

        Returns:
            False for an unknown store or one without chunk methods.
        """
        vectorstore_class = cls.vectorstores.get((type or "").lower())
        return bool(vectorstore_class and vectorstore_class.supports_chunk_edits())

    @classmethod
    def create_vectorstore(cls, type, *args, **kwargs):
        vectorstore_class = cls.vectorstores.get(type.lower())
        if not vectorstore_class:
            raise ValueError(f"No vectorstore class found for type {type}")
        return vectorstore_class(*args, **kwargs)
