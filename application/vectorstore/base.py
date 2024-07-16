from abc import ABC, abstractmethod
import os
from langchain_community.embeddings import (
    HuggingFaceEmbeddings,
    CohereEmbeddings,
    HuggingFaceInstructEmbeddings,
)
from langchain_openai import OpenAIEmbeddings
from application.core.settings import settings

class EmbeddingsSingleton:
    _instances = {}

    @staticmethod
    def get_instance(embeddings_name, *args, **kwargs):
        if embeddings_name not in EmbeddingsSingleton._instances:
            EmbeddingsSingleton._instances[embeddings_name] = EmbeddingsSingleton._create_instance(
                embeddings_name, *args, **kwargs
            )
        return EmbeddingsSingleton._instances[embeddings_name]

    @staticmethod
    def _create_instance(embeddings_name, *args, **kwargs):
        embeddings_factory = {
            "openai_text-embedding-ada-002": OpenAIEmbeddings,
            "huggingface_sentence-transformers/all-mpnet-base-v2": HuggingFaceEmbeddings,
            "huggingface_sentence-transformers-all-mpnet-base-v2": HuggingFaceEmbeddings,
            "huggingface_hkunlp/instructor-large": HuggingFaceInstructEmbeddings,
            "cohere_medium": CohereEmbeddings
        }

        if embeddings_name not in embeddings_factory:
            raise ValueError(f"Invalid embeddings_name: {embeddings_name}")

        return embeddings_factory[embeddings_name](*args, **kwargs)

class BaseVectorStore(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        pass

    def is_azure_configured(self):
        return settings.OPENAI_API_BASE and settings.OPENAI_API_VERSION and settings.AZURE_DEPLOYMENT_NAME

    def _get_embeddings(self, embeddings_name, embeddings_key=None):
        if embeddings_name == "openai_text-embedding-ada-002":
            if self.is_azure_configured():
                os.environ["OPENAI_API_TYPE"] = "azure"
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name,
                    model=settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME
                )
            else:
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name,
                    openai_api_key=embeddings_key
                )
        elif embeddings_name == "cohere_medium":
            embedding_instance = EmbeddingsSingleton.get_instance(
                embeddings_name,
                cohere_api_key=embeddings_key
            )
        elif embeddings_name == "huggingface_sentence-transformers/all-mpnet-base-v2":
            if os.path.exists("./model/all-mpnet-base-v2"):
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name,
                    model_name="./model/all-mpnet-base-v2",
                    model_kwargs={"device": "cpu"}
                )
            else:
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name,
                    model_kwargs={"device": "cpu"}
                )
        else:
            embedding_instance = EmbeddingsSingleton.get_instance(embeddings_name)

        return embedding_instance