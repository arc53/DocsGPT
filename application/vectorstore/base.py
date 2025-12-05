import logging
import os
from abc import ABC, abstractmethod

import requests
from langchain_openai import OpenAIEmbeddings

from application.core.settings import settings


class RemoteEmbeddings:
    """
    Wrapper for remote embeddings API (OpenAI-compatible).
    Used when EMBEDDINGS_BASE_URL is configured.
    """

    def __init__(self, api_url: str, model_name: str, api_key: str = None):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.dimension = None

    def _embed(self, inputs):
        """Send embedding request to remote API."""
        payload = {"inputs": inputs}
        if self.model_name:
            payload["model"] = self.model_name

        response = requests.post(
            self.api_url, headers=self.headers, json=payload, timeout=180
        )
        response.raise_for_status()
        result = response.json()

        if isinstance(result, list):
            if result and isinstance(result[0], list):
                return result
            elif result and all(isinstance(x, (int, float)) for x in result):
                return [result]
            elif not result:
                return []
            else:
                raise ValueError(
                    f"Unexpected list content from remote embeddings API: {result}"
                )
        elif isinstance(result, dict) and "error" in result:
            raise ValueError(f"Remote embeddings API error: {result['error']}")
        else:
            raise ValueError(
                f"Unexpected response format from remote embeddings API: {result}"
            )

    def embed_query(self, query: str):
        """Embed a single query string."""
        embeddings_list = self._embed(query)
        if (
            isinstance(embeddings_list, list)
            and len(embeddings_list) == 1
            and isinstance(embeddings_list[0], list)
        ):
            if self.dimension is None:
                self.dimension = len(embeddings_list[0])
            return embeddings_list[0]
        raise ValueError(
            f"Unexpected result structure after embedding query: {embeddings_list}"
        )

    def embed_documents(self, documents: list):
        """Embed a list of documents."""
        if not documents:
            return []
        embeddings_list = self._embed(documents)
        if self.dimension is None and embeddings_list:
            self.dimension = len(embeddings_list[0])
        return embeddings_list

    def __call__(self, text):
        if isinstance(text, str):
            return self.embed_query(text)
        elif isinstance(text, list):
            return self.embed_documents(text)
        else:
            raise ValueError("Input must be a string or a list of strings")


def _get_embeddings_wrapper():
    """Lazy import of EmbeddingsWrapper to avoid loading SentenceTransformer when using remote embeddings."""
    from application.vectorstore.embeddings_local import EmbeddingsWrapper

    return EmbeddingsWrapper


class EmbeddingsSingleton:
    _instances = {}

    @staticmethod
    def get_instance(embeddings_name, *args, **kwargs):
        if embeddings_name not in EmbeddingsSingleton._instances:
            EmbeddingsSingleton._instances[embeddings_name] = (
                EmbeddingsSingleton._create_instance(embeddings_name, *args, **kwargs)
            )
        return EmbeddingsSingleton._instances[embeddings_name]

    @staticmethod
    def _create_instance(embeddings_name, *args, **kwargs):
        if embeddings_name == "openai_text-embedding-ada-002":
            return OpenAIEmbeddings(*args, **kwargs)

        # Lazy import EmbeddingsWrapper only when needed (avoids loading SentenceTransformer)
        EmbeddingsWrapper = _get_embeddings_wrapper()

        embeddings_factory = {
            "huggingface_sentence-transformers/all-mpnet-base-v2": lambda: EmbeddingsWrapper(
                "sentence-transformers/all-mpnet-base-v2"
            ),
            "huggingface_sentence-transformers-all-mpnet-base-v2": lambda: EmbeddingsWrapper(
                "sentence-transformers/all-mpnet-base-v2"
            ),
            "huggingface_hkunlp/instructor-large": lambda: EmbeddingsWrapper(
                "hkunlp/instructor-large"
            ),
        }

        if embeddings_name in embeddings_factory:
            return embeddings_factory[embeddings_name](*args, **kwargs)
        else:
            return EmbeddingsWrapper(embeddings_name, *args, **kwargs)


class BaseVectorStore(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        """Search for similar documents/chunks in the vectorstore"""
        pass

    @abstractmethod
    def add_texts(self, texts, metadatas=None, *args, **kwargs):
        """Add texts with their embeddings to the vectorstore"""
        pass

    def delete_index(self, *args, **kwargs):
        """Delete the entire index/collection"""
        pass

    def save_local(self, *args, **kwargs):
        """Save vectorstore to local storage"""
        pass

    def get_chunks(self, *args, **kwargs):
        """Get all chunks from the vectorstore"""
        pass

    def add_chunk(self, text, metadata=None, *args, **kwargs):
        """Add a single chunk to the vectorstore"""
        pass

    def delete_chunk(self, chunk_id, *args, **kwargs):
        """Delete a specific chunk from the vectorstore"""
        pass

    def is_azure_configured(self):
        return (
            settings.OPENAI_API_BASE
            and settings.OPENAI_API_VERSION
            and settings.AZURE_DEPLOYMENT_NAME
        )

    def _get_embeddings(self, embeddings_name, embeddings_key=None):
        # Check for remote embeddings first
        if settings.EMBEDDINGS_BASE_URL:
            logging.info(
                f"Using remote embeddings API at: {settings.EMBEDDINGS_BASE_URL}"
            )
            cache_key = f"remote_{settings.EMBEDDINGS_BASE_URL}_{embeddings_name}"
            if cache_key not in EmbeddingsSingleton._instances:
                EmbeddingsSingleton._instances[cache_key] = RemoteEmbeddings(
                    api_url=settings.EMBEDDINGS_BASE_URL,
                    model_name=embeddings_name,
                    api_key=embeddings_key,
                )
            return EmbeddingsSingleton._instances[cache_key]

        if embeddings_name == "openai_text-embedding-ada-002":
            if self.is_azure_configured():
                os.environ["OPENAI_API_TYPE"] = "azure"
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name, model=settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME
                )
            else:
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name, openai_api_key=embeddings_key
                )
        elif embeddings_name == "huggingface_sentence-transformers/all-mpnet-base-v2":
            possible_paths = [
                "/app/models/all-mpnet-base-v2",  # Docker absolute path
                "./models/all-mpnet-base-v2",  # Relative path
            ]
            local_model_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    local_model_path = path
                    logging.info(f"Found local model at path: {path}")
                    break
                else:
                    logging.info(f"Path does not exist: {path}")
            if local_model_path:
                embedding_instance = EmbeddingsSingleton.get_instance(
                    local_model_path,
                )
            else:
                logging.warning(
                    f"Local model not found in any of the paths: {possible_paths}. Falling back to HuggingFace download."
                )
                embedding_instance = EmbeddingsSingleton.get_instance(
                    embeddings_name,
                )
        else:
            embedding_instance = EmbeddingsSingleton.get_instance(embeddings_name)
        return embedding_instance
