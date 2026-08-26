"""Local embeddings via FastEmbed (ONNX Runtime).

Replaces the previous SentenceTransformer implementation. Both run the same
weights; FastEmbed reaches them through ONNX Runtime instead of torch, which
removes torch, transformers and sentence-transformers from the dependency set
and measurably reduces both resident memory and import cost.

The swap is numerically transparent for existing indexes: embedding the same
text with SentenceTransformer and with FastEmbed's ONNX graph of the same
model returns vectors at cosine 1.0, so an mpnet index built before this
change keeps working unchanged.

Models are described in :mod:`application.vectorstore.model_registry`. A name
the registry does not know is treated as a Hugging Face repository, which is
what someone configuring an arbitrary model expects.
"""

import logging
import threading
from typing import Any, List, Optional

from application.core.settings import settings
from application.vectorstore.model_registry import EmbeddingModel, resolve, known_names

logger = logging.getLogger(__name__)

# ``add_custom_model`` mutates a process-global registry inside FastEmbed, so
# repeated registration of the same name is both wasteful and racy under the
# thread pool the API serves requests from.
_registered: set = set()
_register_lock = threading.Lock()

# Assumed layout for a model the registry does not describe.
_FALLBACK_ONNX_FILE = "onnx/model.onnx"
_FALLBACK_POOLING = "mean"


def _pooling_type(pooling: str):
    """Map our ``"cls"``/``"mean"`` spelling onto FastEmbed's enum."""
    from fastembed.common.model_description import PoolingType

    return {"cls": PoolingType.CLS, "mean": PoolingType.MEAN}[pooling]


def _register(model: EmbeddingModel) -> None:
    """Teach FastEmbed about a model, exactly once per process."""
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource

    with _register_lock:
        if model.repo in _registered:
            return
        TextEmbedding.add_custom_model(
            model=model.repo,
            pooling=_pooling_type(model.pooling),
            normalization=model.normalize,
            sources=ModelSource(hf=model.repo),
            dim=model.dimension,
            model_file=model.onnx_file,
        )
        _registered.add(model.repo)


def _spec_for(model_name: str) -> EmbeddingModel:
    """Registry entry for ``model_name``, or a best-effort one for a raw repo.

    Args:
        model_name: Configured ``EMBEDDINGS_NAME``.

    Returns:
        A registry entry. For an unregistered name the returned entry assumes
        the standard Hugging Face ONNX layout and mean pooling, and carries
        ``dimension = 0`` so the caller knows to probe for the real width.
    """
    spec = resolve(model_name)
    if spec is not None:
        return spec
    logger.info(
        "Embedding model %r is not in the registry (known: %s); treating it as a "
        "Hugging Face repository with %s and %s pooling.",
        model_name,
        ", ".join(known_names()),
        _FALLBACK_ONNX_FILE,
        _FALLBACK_POOLING,
    )
    return EmbeddingModel(
        name=model_name,
        dimension=0,
        max_input_tokens=512,
        pooling=_FALLBACK_POOLING,
        normalize=True,
        repo=model_name,
        onnx_file=_FALLBACK_ONNX_FILE,
    )


class EmbeddingsWrapper:
    """Runs an embedding model locally through FastEmbed.

    Exposes the ``embed_query``/``embed_documents``/``dimension`` interface the
    vector stores rely on, matching ``RemoteEmbeddings`` and ``OpenAIEmbeddings``.
    """

    def __init__(self, model_name: str, *args: Any, **kwargs: Any) -> None:
        """Load ``model_name`` locally.

        Args:
            model_name: Registry name, alias, or a Hugging Face repository id.

        Raises:
            RuntimeError: If the model cannot be loaded, with the configured
                name and the registry's known names in the message.
        """
        from fastembed import TextEmbedding

        self.spec = _spec_for(model_name)
        logger.info("Loading embeddings model %s via FastEmbed", self.spec.repo)
        try:
            _register(self.spec)
            init_kwargs = {"model_name": self.spec.repo}
            threads = getattr(settings, "EMBEDDINGS_THREADS", None)
            if isinstance(threads, int) and threads > 0:
                init_kwargs["threads"] = threads
            cache_dir = getattr(settings, "EMBEDDINGS_CACHE_DIR", None)
            if cache_dir:
                init_kwargs["cache_dir"] = cache_dir
            self.model = TextEmbedding(**init_kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load embeddings model {model_name!r} via FastEmbed: "
                f"{exc}. Known models: {', '.join(known_names())}."
            ) from exc

        self.dimension = self.spec.dimension or self._probe_dimension()
        logger.info("Embeddings model ready (dimension=%d)", self.dimension)

    def _probe_dimension(self) -> int:
        """Determine the vector width of a model the registry does not describe."""
        return len(self.embed_query("dimension probe"))

    @property
    def tokenizer(self):
        """The model's own tokenizer, so chunking can count in its units."""
        return self.model.model.tokenizer

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query string."""
        return self.embed_documents([query])[0]

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """Embed a list of documents, preserving input order.

        Inputs are grouped by length before batching. ONNX needs a rectangular
        tensor, so every input in a batch is padded up to the longest one in
        it; with mixed lengths that padding is most of the work. Grouping
        similar lengths together measured 19% faster and 45% lower peak memory
        on production-sized chunks, and at full context an unsorted batch of 4
        was slower than no batching at all.

        The original order is restored before returning, so callers zipping
        these against their texts are unaffected.
        """
        if not documents:
            return []
        batch_size: Optional[int] = None
        raw = getattr(settings, "EMBEDDINGS_BATCH_SIZE", None)
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            batch_size = raw

        documents = list(documents)
        if batch_size is None or len(documents) <= batch_size:
            # One batch either way: sorting would only add work.
            return [v.tolist() for v in self.model.embed(documents, batch_size=batch_size)]

        order = sorted(range(len(documents)), key=lambda i: len(documents[i]))
        grouped = [documents[i] for i in order]
        vectors = [v.tolist() for v in self.model.embed(grouped, batch_size=batch_size)]

        restored: List[Optional[List[float]]] = [None] * len(documents)
        for position, original_index in enumerate(order):
            restored[original_index] = vectors[position]
        return restored

    def __call__(self, text):
        if isinstance(text, str):
            return self.embed_query(text)
        elif isinstance(text, list):
            return self.embed_documents(text)
        raise ValueError("Input must be a string or a list of strings")
