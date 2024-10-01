from application.retriever.classic_rag import ClassicRAG
from application.retriever.duckduck_search import DuckDuckSearch
from application.retriever.brave_search import BraveRetSearch



class RetrieverCreator:
    retrievers = {
        'classic': ClassicRAG,
        'duckduck_search': DuckDuckSearch,
        'brave_search': BraveRetSearch,
        'default': ClassicRAG
    }

    @classmethod
    def create_retriever(cls, type, *args, **kwargs):
        retiever_class = cls.retrievers.get(type.lower())
        if not retiever_class:
            raise ValueError(f"No retievers class found for type {type}")
        return retiever_class(*args, **kwargs)