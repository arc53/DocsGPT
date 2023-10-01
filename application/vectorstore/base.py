from abc import ABC, abstractmethod
import os
from langchain.embeddings import (
    OpenAIEmbeddings,
    HuggingFaceEmbeddings,
    CohereEmbeddings,
    HuggingFaceInstructEmbeddings,
)
from application.core.settings import settings

class BaseVectorStore(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        pass

    def is_azure_configured(self):
        return settings.OPENAI_API_BASE and settings.OPENAI_API_VERSION and settings.AZURE_DEPLOYMENT_NAME

    def _get_docsearch(self, embeddings_name, embeddings_key=None):
        embeddings_factory = {
            "openai_text-embedding-ada-002": OpenAIEmbeddings,
            "huggingface_sentence-transformers/all-mpnet-base-v2": HuggingFaceEmbeddings,
            "huggingface_hkunlp/instructor-large": HuggingFaceInstructEmbeddings,
            "cohere_medium": CohereEmbeddings
        }
        
        if embeddings_name not in embeddings_factory:
            raise ValueError(f"Invalid embeddings_name: {embeddings_name}")

        if embeddings_name == "openai_text-embedding-ada-002":
            if self.is_azure_configured():
                os.environ["OPENAI_API_TYPE"] = "azure"
                embedding_instance = embeddings_factory[embeddings_name](
                    model=settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME
                )
            else:
                embedding_instance = embeddings_factory[embeddings_name](
                    openai_api_key=embeddings_key
                )
        elif embeddings_name == "cohere_medium":
            embedding_instance = embeddings_factory[embeddings_name](
                cohere_api_key=embeddings_key
            )
        else:
            embedding_instance = embeddings_factory[embeddings_name]()
            
        return embedding_instance

