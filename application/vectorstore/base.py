import logging
import os
from abc import ABC, abstractmethod

import requests
from langchain_openai import OpenAIEmbeddings

from application.core.settings import settings
from application.utils import get_encoding


class RemoteEmbeddings:
    """
    Wrapper for remote embeddings API (OpenAI-compatible).
    Used when EMBEDDINGS_BASE_URL is configured.
    Sends requests to {base_url}/v1/embeddings in OpenAI format.
    """

    def __init__(self, api_url: str, model_name: str, api_key: str = None):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.dimension = 768

    def _truncate_inputs(self, inputs):
        """Clip each input to ``EMBEDDINGS_MAX_INPUT_TOKENS`` tokens.

        The remote server (e.g. llama.cpp) hard-rejects any single input
        larger than its physical batch size with a 500. When the setting is
        configured, each input is truncated to that many tokens before the
        request and the overflow is dropped (lossy by design). Token counts
        use the shared tiktoken encoding, which differs from the server's
        tokenizer, so set the limit with headroom under the server's true
        limit to absorb tokenizer skew.

        Args:
            inputs: A single string or a list of strings to embed.

        Returns:
            The inputs with each string clipped to the token limit, or the
            inputs unchanged when the limit is unset or non-positive.
        """
        limit = settings.EMBEDDINGS_MAX_INPUT_TOKENS
        if not limit or limit <= 0:
            return inputs

        encoding = get_encoding()

        def clip(text):
            if not isinstance(text, str):
                return text
            tokens = encoding.encode(text)
            if len(tokens) <= limit:
                return text
            logging.warning(
                "Truncating remote embeddings input from %d to %d tokens (%d dropped)",
                len(tokens),
                limit,
                len(tokens) - limit,
            )
            return encoding.decode(tokens[:limit])

        if isinstance(inputs, list):
            return [clip(text) for text in inputs]
        return clip(inputs)

    def _embed(self, inputs):
        """Send embedding request to remote API in OpenAI-compatible format."""
        inputs = self._truncate_inputs(inputs)
        payload = {"input": inputs}
        if self.model_name:
            payload["model"] = self.model_name

        url = f"{self.api_url}/v1/embeddings"
        response = requests.post(url, headers=self.headers, json=payload, timeout=180)
        response.raise_for_status()
        result = response.json()

        # Handle OpenAI-compatible response format
        if isinstance(result, dict):
            if "error" in result:
                raise ValueError(f"Remote embeddings API error: {result['error']}")
            if "data" in result:
                # Sort by index to ensure correct order
                data = sorted(result["data"], key=lambda x: x.get("index", 0))
                return [item["embedding"] for item in data]
            raise ValueError(
                f"Unexpected response format from remote embeddings API: {result}"
            )
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
    def _remote_instance(embeddings_name, embeddings_key=None):
        """Return a cached ``RemoteEmbeddings`` for the configured remote API.

        Centralizes the ``EMBEDDINGS_BASE_URL`` dispatch so every caller —
        including code that calls :meth:`get_instance` directly (GraphRAG,
        semantic chunking) rather than via
        :meth:`BaseVectorStore._get_embeddings` — routes to the remote
        embeddings server instead of attempting a local model download.

        Args:
            embeddings_name: Model name forwarded to the remote API.
            embeddings_key: Optional API key; falls back to
                ``settings.EMBEDDINGS_KEY`` when not provided.

        Returns:
            RemoteEmbeddings: Shared instance keyed by base URL and model name.
        """
        api_key = embeddings_key if embeddings_key is not None else settings.EMBEDDINGS_KEY
        cache_key = f"remote_{settings.EMBEDDINGS_BASE_URL}_{embeddings_name}"
        if cache_key not in EmbeddingsSingleton._instances:
            EmbeddingsSingleton._instances[cache_key] = RemoteEmbeddings(
                api_url=settings.EMBEDDINGS_BASE_URL,
                model_name=embeddings_name,
                api_key=api_key,
            )
        return EmbeddingsSingleton._instances[cache_key]

    @staticmethod
    def get_instance(embeddings_name, *args, **kwargs):
        if settings.EMBEDDINGS_BASE_URL:
            return EmbeddingsSingleton._remote_instance(embeddings_name)
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

    def keyword_search(self, question, k=10):
        """Keyword/full-text search.

        Default returns no results so hybrid retrieval degrades to vector-only
        on stores without keyword support. Override in stores that support it.
        """
        return []

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

    def delete_chunks_by_source_path(self, path) -> int:
        """Delete every chunk whose ``metadata.source`` equals ``path``.

        Default implementation iterates ``get_chunks()`` and deletes the
        matches via ``delete_chunk()`` — works for any store. Override with a
        single targeted statement where the store supports it. Returns the
        number of chunks deleted.
        """
        deleted = 0
        for chunk in self.get_chunks() or []:
            if (chunk.get("metadata") or {}).get("source") == path:
                if self.delete_chunk(chunk.get("doc_id")):
                    deleted += 1
        return deleted

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
            return EmbeddingsSingleton._remote_instance(embeddings_name, embeddings_key)

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
