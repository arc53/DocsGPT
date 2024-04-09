from application.retriever.classic_rag import ClassicRAG



class RetrieverCreator:
    retievers = {
        'classic': ClassicRAG,
    }

    @classmethod
    def create_retriever(cls, type, *args, **kwargs):
        retiever_class = cls.retievers.get(type.lower())
        if not retiever_class:
            raise ValueError(f"No retievers class found for type {type}")
        return retiever_class(*args, **kwargs)