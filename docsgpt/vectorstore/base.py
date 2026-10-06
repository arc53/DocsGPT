import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from typing import List, Optional

import requests

from docsgpt.core.settings import settings
from docsgpt.vectorstore.embeddings_openai import OpenAIEmbeddings
from docsgpt.vectorstore.model_registry import (
    dimension_for,
    max_input_tokens_for,
    resolve,
)


def _key_fingerprint(api_key: Optional[str]) -> str:
    """Non-reversible tag for an API key, so it can be named without being exposed.

    Part of every cached client's identity: the cache used to be keyed without
    the key, so the first caller's key served every later caller in the
    process. Also what an auth failure logs in place of the key.

    Args:
        api_key: The key, or ``None``/empty for none.

    Returns:
        str: The first 16 hex characters of the key's SHA-256, or ``"nokey"``.
    """
    if not api_key:
        return "nokey"
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _embeddings_name_is_explicit() -> bool:
    """True when ``EMBEDDINGS_NAME`` names a model somebody actually chose.

    Not ``model_fields_set``: pydantic marks a field as set for any value that
    reached it, including one read from ``.env``, and every setup script has
    always written ``EMBEDDINGS_NAME`` unconditionally. An install carrying the
    legacy name a script wrote years ago would read as a deliberate choice and
    lend a remote server that model's context window.
    """
    fields = getattr(type(settings), "model_fields", None)
    if not isinstance(fields, dict):
        return False
    field = fields.get("EMBEDDINGS_NAME")
    if field is None:
        return False
    return settings.EMBEDDINGS_NAME != field.default


class RemoteEmbeddings:
    """
    Wrapper for remote embeddings API (OpenAI-compatible).
    Used when EMBEDDINGS_BASE_URL is configured.
    Sends requests to {base_url}/v1/embeddings in OpenAI format.
    """

    def __init__(self, api_url: str, model_name: str, api_key: str = None):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.key_fingerprint = _key_fingerprint(api_key)
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
        from docsgpt.parser.tokenization import get_token_counter

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
        if response.status_code in (401, 403):
            # A rejected key is configuration, not a transient fault: every
            # later request fails the same way until the key is fixed.
            logging.error(
                "embeddings_auth_failed status_code=%s model=%s key_fingerprint=%s: "
                "the embeddings endpoint rejected this process's key; check EMBEDDINGS_KEY",
                response.status_code,
                self.model_name,
                self.key_fingerprint,
                extra={
                    "event": "embeddings_auth_failed",
                    "status_code": response.status_code,
                    "key_fingerprint": self.key_fingerprint,
                },
            )
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
    from docsgpt.vectorstore.embeddings_local import EmbeddingsWrapper

    return EmbeddingsWrapper


class EmbeddingsSingleton:
    """Process-wide cache of embedding runners, one per model (or remote endpoint).

    Each runner is built once, under ``_lock``: concurrent first requests
    would otherwise each load the model, holding several copies in memory.
    """

    _instances = {}
    _lock = threading.Lock()

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
            RemoteEmbeddings: Shared instance keyed by base URL, model name and
            a fingerprint of the key, so a caller holding a different key never
            gets a client that authenticates with someone else's.
        """
        api_key = embeddings_key if embeddings_key is not None else settings.EMBEDDINGS_KEY
        cache_key = (
            f"remote_{settings.EMBEDDINGS_BASE_URL}_{embeddings_name}_{_key_fingerprint(api_key)}"
        )
        return EmbeddingsSingleton._get_or_create(
            cache_key,
            lambda: RemoteEmbeddings(
                api_url=settings.EMBEDDINGS_BASE_URL,
                model_name=embeddings_name,
                api_key=api_key,
            ),
        )

    @staticmethod
    def _get_or_create(cache_key, factory):
        """Return the cached runner for ``cache_key``, building it once under the lock."""
        instance = EmbeddingsSingleton._instances.get(cache_key)
        if instance is not None:
            return instance
        with EmbeddingsSingleton._lock:
            instance = EmbeddingsSingleton._instances.get(cache_key)
            if instance is None:
                instance = factory()
                EmbeddingsSingleton._instances[cache_key] = instance
            return instance

    @staticmethod
    def get_instance(embeddings_name, *args, **kwargs):
        if settings.EMBEDDINGS_BASE_URL:
            # A direct caller hands its key over positionally or as
            # ``openai_api_key``; either wins over EMBEDDINGS_KEY.
            explicit = kwargs.get("openai_api_key", args[0] if args else None)
            return EmbeddingsSingleton._remote_instance(
                embeddings_name, explicit if isinstance(explicit, str) else None
            )
        # A keyed runner (OpenAI) is cached per key. A local model takes no key
        # and stays under its bare name, which the boot hook evicts it by.
        key = kwargs.get("openai_api_key")
        cache_key = embeddings_name if key is None else f"{embeddings_name}_{_key_fingerprint(key)}"
        return EmbeddingsSingleton._get_or_create(
            cache_key,
            lambda: EmbeddingsSingleton._create_instance(embeddings_name, *args, **kwargs),
        )

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


def _delegation_enabled() -> bool:
    """True when this process should embed on the worker rather than locally.

    Compared against ``True`` rather than coerced: tests patch ``settings``
    with a ``MagicMock``, whose every attribute is a truthy object, and
    ``bool()`` on that would silently route them through the broker.
    """
    return settings.EMBEDDINGS_DELEGATE_TO_WORKER is True


def get_embeddings(
    embeddings_name: Optional[str] = None, embeddings_key: Optional[str] = None
):
    """Resolve the configured embeddings instance. The single entry point.

    Callers that reach for :meth:`EmbeddingsSingleton.get_instance` directly
    skip the remote dispatch and the OpenAI/Azure key handling. Route every
    caller through here.

    With ``EMBEDDINGS_DELEGATE_TO_WORKER`` this returns a client that runs the
    model on the Celery worker, so an API process never loads one. The client
    embeds locally when it finds itself inside a worker task, so the worker is
    unaffected.

    Args:
        embeddings_name: Model name; defaults to ``settings.EMBEDDINGS_NAME``.
        embeddings_key: API key; defaults to ``settings.EMBEDDINGS_KEY``.

    Returns:
        The shared embeddings instance for the resolved model.
    """
    embeddings_name = embeddings_name or settings.EMBEDDINGS_NAME
    if not settings.EMBEDDINGS_BASE_URL and _delegation_enabled():
        # Keyed by the key too: inside a worker the client embeds locally with
        # the key it was built with. A dispatched embed carries no key -- the
        # worker embeds with its own EMBEDDINGS_KEY, which it shares with this
        # process -- so no secret ever travels over the broker.
        api_key = embeddings_key if embeddings_key is not None else settings.EMBEDDINGS_KEY

        def _delegated():
            from docsgpt.vectorstore.embeddings_delegated import DelegatedEmbeddings

            return DelegatedEmbeddings(embeddings_name, api_key)

        return EmbeddingsSingleton._get_or_create(
            f"delegated_{embeddings_name}_{_key_fingerprint(api_key)}", _delegated
        )
    return build_local_embeddings(embeddings_name, embeddings_key)


def build_local_embeddings(
    embeddings_name: Optional[str] = None, embeddings_key: Optional[str] = None
):
    """Resolve the embeddings instance that runs in *this* process.

    Bypasses worker delegation, so it is what the worker's embed task and the
    boot hook use. Everything else should call :func:`get_embeddings`.

    Args:
        embeddings_name: Model name; defaults to ``settings.EMBEDDINGS_NAME``.
        embeddings_key: API key; defaults to ``settings.EMBEDDINGS_KEY``.

    Returns:
        The shared in-process embeddings instance for the resolved model.
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

    # Match through the registry, not on the canonical string: the bare
    # ``text-embedding-ada-002`` alias resolves here too, and skipping this
    # branch would drop the Azure deployment name and the API key.
    spec = resolve(embeddings_name)
    if spec is not None and spec.provider == "openai":
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


class InvalidChunkMetadataError(ValueError):
    """Chunk metadata the store cannot write, such as a key it reserves.

    A client-input error, distinct from a store or embedding failure: the
    chunk routes answer it with a 400 rather than a 500.
    """


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

    def update_chunk(self, chunk_id: str, text: str, metadata: dict) -> str:
        """Replace a chunk's text and metadata, returning the id it is now under.

        Stores that can rewrite a row in place override this and keep both the
        id and the chunk's position in :meth:`get_chunks`. This default works
        for any store but re-adds the chunk and deletes the old one, so the
        returned id differs and the chunk moves; callers holding the old id
        (graph links, for one) must follow the returned id.

        Args:
            chunk_id: Id of the chunk to replace.
            text: The chunk's new text.
            metadata: The chunk's complete new metadata.

        Returns:
            The id the updated chunk is stored under.

        Raises:
            RuntimeError: The old chunk could not be deleted. The new chunk is
                deleted again (best effort) so no duplicate is left behind.
        """
        new_chunk_id = self.add_chunk(text, metadata)
        delete_error: Optional[Exception] = None
        try:
            deleted = self.delete_chunk(chunk_id)
        except Exception as err:
            deleted, delete_error = False, err
        if deleted:
            return new_chunk_id
        try:
            self.delete_chunk(new_chunk_id)
        except Exception:
            logging.error(
                "Failed to roll back new chunk %s after old chunk %s could not be deleted",
                new_chunk_id,
                chunk_id,
                exc_info=True,
            )
        raise RuntimeError(f"Failed to delete old chunk {chunk_id} during update") from delete_error

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

    def _scan_chunks(self) -> List[dict]:
        """Every chunk of this source, raising when the store cannot list them.

        ``get_chunks`` reads a store error as "no chunks" in several stores;
        a lookup must not, or a citation that is only unreachable would tell
        the reader its passage is gone. Stores that swallow errors in
        ``get_chunks`` override this with the unguarded listing.

        Returns:
            list[dict]: ``{"doc_id", "text", "metadata"}`` per chunk.

        Raises:
            NotImplementedError: The store has no ``get_chunks``.
        """
        chunks = self.get_chunks()
        if chunks is None:
            raise NotImplementedError(f"{type(self).__name__} cannot list its chunks")
        return chunks

    def get_chunk_by_key(self, key: str, excerpt: Optional[str] = None) -> Optional[dict]:
        """Return the chunk whose text hashes to ``key``, or ``None``.

        ``key`` is a citation's ``chunk_key`` (the MD5 of the chunk text, see
        ``docsgpt.retriever.labels.chunk_key``). Default implementation hashes
        every chunk in one pass of :meth:`_scan_chunks`; override with a query
        where the store can hash server-side. Duplicate texts share a key, and
        the first copy wins. A re-chunked source no longer has the key, so the
        same pass also notes the first chunk containing ``excerpt``, the start
        of the passage the answer saved.

        Args:
            key: The chunk key, 32 lowercase hex characters.
            excerpt: Text to fall back on, matched case-insensitively.

        Returns:
            dict | None: ``{"doc_id", "text", "metadata"}`` for the chunk.

        Raises:
            NotImplementedError: The store cannot list its chunks.
        """
        from docsgpt.retriever.labels import chunk_key

        needle = (excerpt or "").strip().lower()
        by_excerpt = None
        for chunk in self._scan_chunks():
            text = chunk.get("text") or ""
            if chunk_key(text) == key:
                return _chunk_row(chunk)
            if needle and by_excerpt is None and needle in text.lower():
                by_excerpt = chunk
        return _chunk_row(by_excerpt) if by_excerpt else None

    def is_azure_configured(self):
        """Kept for compatibility; delegates to the module-level check."""
        return _azure_configured()

    def _get_embeddings(self, embeddings_name, embeddings_key=None):
        """Resolve embeddings for this store; see :func:`get_embeddings`."""
        return get_embeddings(embeddings_name, embeddings_key)


def _chunk_row(chunk: dict) -> dict:
    """The ``{"doc_id", "text", "metadata"}`` shape a chunk lookup returns."""
    return {
        "doc_id": str(chunk.get("doc_id", "")),
        "text": chunk.get("text", ""),
        "metadata": chunk.get("metadata") or {},
    }
