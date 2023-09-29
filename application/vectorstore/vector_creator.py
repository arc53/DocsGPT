from application.vectorstore.faiss import FaissStore
from application.vectorstore.elasticsearch import ElasticsearchStore


class VectorCreator:
    vectorstores = {
        'faiss': FaissStore,
        'elasticsearch':ElasticsearchStore
    }

    @classmethod
    def create_vectorstore(cls, type, *args, **kwargs):
        vectorstore_class = cls.vectorstores.get(type.lower())
        if not vectorstore_class:
            raise ValueError(f"No vectorstore class found for type {type}")
        return vectorstore_class(*args, **kwargs)