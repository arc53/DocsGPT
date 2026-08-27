import logging
from abc import ABC, abstractmethod
from typing import Optional

import requests

from application.core.settings import settings
from application.vectorstore.embeddings_openai import OpenAIEmbeddings
from application.vectorstore.model_registry import (
    dimension_for,
    max_input_tokens_for,
    resolve,
)


def _embeddings_name_is_explicit() -> bool:
    """True when ``EMBEDDINGS_NAME`` was configured rather than defaulted."""
    return "EMBEDDINGS_NAME" in getattr(settings, "model_fields_set", set())


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
        # Width comes from the registry. This used to be a hardcoded 768 that
        # ``embed_query`` claimed to correct on first use -- but the correction
        # was guarded by ``if self.dimension is None``, which the hardcode made
        # unreachable, so a remote model of any other width silently produced a
        # ``vector(768)`` column. ``None`` here means "unknown", and the probe
        # below now genuinely runs.
        self.dimension = dimension_for(model_name)

    def _token_counter(self):
        """Counter matching the remote model's tokenizer, cached per process."""
        from application.parser.tokenization import get_token_counter

        return get_token_counter(self.model_name)

    def _resolve_input_limit(self):
        """Token ceiling for a single embed input, or ``None`` for no limit.

        ``EMBEDDINGS_MAX_INPUT_TOKENS`` wins when set. Otherwise a registered
        model contributes its own context window, so a request that the server
        would reject -- or silently truncate -- is clipped here instead of
        being sent and paid for.

        That fallback needs the name to mean something. For a remote server it
        is only a label forwarded as the ``model`` field, so the settings
        default must not lend the server mpnet's 384-token window: a name
        nobody chose describes nothing, and clipping on it would silently
        discard most of every chunk.
        """
        configured = settings.EMBEDDINGS_MAX_INPUT_TOKENS
        if configured and configured > 0:
            return configured
        if not _embeddings_name_is_explicit():
            return None
        model_limit = max_input_tokens_for(self.model_name)
        return model_limit if model_limit and model_limit > 0 else None

    def _truncate_inputs(self, inputs):
        """Clip each input to the resolved token limit.

        The remote server (e.g. llama.cpp) hard-rejects any single input
        larger than its physical batch size with a 500, so oversized inputs are
        truncated before the request and the overflow is dropped (lossy by
        design).

        Counting uses the embedding model's own tokenizer where it is known, so
        the limit and the count are in the same unit. When it is not -- an
        unregistered model, or no tokenizer available -- this falls back to
        tiktoken, and the limit should then carry headroom to absorb the skew
        between the two tokenizers.

        Args:
            inputs: A single string or a list of strings to embed.

        Returns:
            The inputs with each string clipped to the token limit, or the
            inputs unchanged when no limit applies.
        """
        limit = self._resolve_input_limit()
        if not limit:
            return inputs

        counter = self._token_counter()

        def clip(text):
            if not isinstance(text, str):
                return text
            count = counter.count(text)
            if count <= limit:
                return text
            logging.warning(
                "Truncating remote embeddings input from %d to %d tokens (%d dropped)",
                count,
                limit,
                count - limit,
            )
            pieces = counter.split(text, limit)
            return pieces[0] if pieces else text

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
    """Lazy import of EmbeddingsWrapper, so a remote setup never loads ONNX."""
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
        """Build the runner for ``embeddings_name``, per the model registry.

        The registry replaced a hand-maintained factory dict whose entries
        existed only to rewrite a configured name into a repository id. That
        rewrite is now a registry field, so an unknown name needs no entry
        here: it is passed through as a Hugging Face repository.
        """
        spec = resolve(embeddings_name)
        if spec is not None and spec.provider == "openai":
            return OpenAIEmbeddings(*args, **kwargs)

        EmbeddingsWrapper = _get_embeddings_wrapper()
        if spec is not None and (args or kwargs):
            logging.debug(
                "Dropping %d positional and %d keyword argument(s) for registered "
                "embeddings model %s: the registry supplies its configuration.",
                len(args),
                len(kwargs),
                embeddings_name,
            )
            return EmbeddingsWrapper(embeddings_name)
        return EmbeddingsWrapper(embeddings_name, *args, **kwargs)


def _azure_configured() -> bool:
    """True when the Azure OpenAI deployment settings are all present."""
    return bool(
        settings.OPENAI_API_BASE
        and settings.OPENAI_API_VERSION
        and settings.AZURE_DEPLOYMENT_NAME
    )


def get_embeddings(
    embeddings_name: Optional[str] = None, embeddings_key: Optional[str] = None
):
    """Resolve the configured embeddings instance. The single entry point.

    Callers that reach for :meth:`EmbeddingsSingleton.get_instance` directly
    skip the remote dispatch and the OpenAI/Azure key handling. Route every
    caller through here.

    Args:
        embeddings_name: Model name; defaults to ``settings.EMBEDDINGS_NAME``.
        embeddings_key: API key; defaults to ``settings.EMBEDDINGS_KEY``.

    Returns:
        The shared embeddings instance for the resolved model.
    """
    embeddings_name = embeddings_name or settings.EMBEDDINGS_NAME
    embeddings_key = (
        embeddings_key if embeddings_key is not None else settings.EMBEDDINGS_KEY
    )

    # Check for remote embeddings first
    if settings.EMBEDDINGS_BASE_URL:
        logging.info(
            f"Using remote embeddings API at: {settings.EMBEDDINGS_BASE_URL}"
        )
        return EmbeddingsSingleton._remote_instance(embeddings_name, embeddings_key)

    if embeddings_name == "openai_text-embedding-ada-002":
        if _azure_configured():
            embedding_instance = EmbeddingsSingleton.get_instance(
                embeddings_name, model=settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME
            )
        else:
            embedding_instance = EmbeddingsSingleton.get_instance(
                embeddings_name, openai_api_key=embeddings_key
            )
    else:
        # No per-model branching: the registry resolves names and FastEmbed
        # caches artifacts under EMBEDDINGS_CACHE_DIR, which is where the
        # image warms them at build time.
        embedding_instance = EmbeddingsSingleton.get_instance(embeddings_name)
    return embedding_instance


class BaseVectorStore(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        """Search for similar documents/chunks in the vectorstore.

        Implementations accept an optional ``query_vector`` kwarg: the query
        already embedded by the caller, so a multi-source retrieval embeds once
        instead of once per store. A store that cannot use it must still swallow
        the kwarg (every signature here ends in ``**kwargs``) and embed the
        question itself.
        """
        pass

    def keyword_search(self, question, k=10):
        """Keyword/full-text search.

        Default returns no results so hybrid retrieval degrades to vector-only
        on stores without keyword support. Override in stores that support it.
        """
        return []

    # What ``search_with_scores`` reports, so a caller can label the number.
    # ``cosine_similarity`` is higher-is-better in [0, 1]; ``l2_distance`` is
    # lower-is-better and unbounded. None = this store reports no score.
    score_kind = None

    def search_with_scores(self, question, k=2, *args, **kwargs):
        """Search, pairing each hit with its raw relevance score.

        Default pairs every hit from :meth:`search` with ``None`` so stores that
        surface no score still satisfy the contract. Stores that already compute
        one override this and set :attr:`score_kind`.

        Returns:
            A list of ``(Document, score | None)`` in the same rank order
            :meth:`search` would return.
        """
        return [
            (doc, None) for doc in self.search(question, k, *args, **kwargs) or []
        ]

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
        """Kept for compatibility; delegates to the module-level check."""
        return _azure_configured()

    def _get_embeddings(self, embeddings_name, embeddings_key=None):
        """Resolve embeddings for this store; see :func:`get_embeddings`."""
        return get_embeddings(embeddings_name, embeddings_key)
