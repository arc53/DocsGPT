"""Local embeddings via FastEmbed (ONNX Runtime).

Replaces the previous SentenceTransformer implementation. Both run the same
weights; FastEmbed reaches them through ONNX Runtime instead of torch, which
removes torch, transformers and sentence-transformers from the dependency set
and measurably reduces both resident memory and import cost.

The swap is numerically transparent for existing indexes: embedding the same
text with SentenceTransformer and with FastEmbed's fp32 ONNX graph of mpnet
returns vectors at cosine 1.0, so an mpnet index built before this change
keeps working unchanged. That result is specific to the fp32 graph -- the
granite entries run an int8-quantised one and are not bit-comparable to a
fp32 index of the same model.

Models are described in :mod:`application.vectorstore.model_registry`. A name
the registry does not know is treated as a Hugging Face repository, which is
what someone configuring an arbitrary model expects; how to run it is read
from the repository itself rather than assumed.
"""

import json
import logging
import threading
from dataclasses import replace
from typing import Any, List, Optional

from application.core.settings import settings
from application.vectorstore.model_registry import EmbeddingModel, resolve, known_names

logger = logging.getLogger(__name__)

# ``add_custom_model`` mutates a process-global registry inside FastEmbed, so
# repeated registration of the same name is both wasteful and racy under the
# thread pool the API serves requests from.
_registered: set = set()
_register_lock = threading.Lock()

# Last-resort layout for a repository that declares nothing about itself.
_FALLBACK_ONNX_FILE = "onnx/model.onnx"
_FALLBACK_POOLING = "mean"

# Sentence-transformers records how a model turns token vectors into one
# vector, and whether it normalises the result, as files in the repository.
# Reading them is the difference between running a model and running something
# that merely shares its weights: mean-pooling a CLS model returns vectors at
# cosine ~0.95 to the correct ones -- close enough to look like it works, far
# enough to degrade retrieval, and silent either way.
_POOLING_CONFIG = "1_Pooling/config.json"
_MODULES_CONFIG = "modules.json"


def _pooling_type(pooling: str):
    """Map our ``"cls"``/``"mean"`` spelling onto FastEmbed's enum."""
    from fastembed.common.model_description import PoolingType

    return {"cls": PoolingType.CLS, "mean": PoolingType.MEAN}[pooling]


def _is_builtin(repo: str) -> bool:
    """True when FastEmbed already ships a description for ``repo``."""
    from fastembed import TextEmbedding

    lowered = repo.lower()
    return any(
        str(entry.get("model", "")).lower() == lowered
        for entry in TextEmbedding.list_supported_models()
    )


def _register(model: EmbeddingModel) -> None:
    """Teach FastEmbed about a model, exactly once per process."""
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource

    with _register_lock:
        if model.repo in _registered:
            return
        if _is_builtin(model.repo):
            # ``add_custom_model`` refuses a name FastEmbed already ships, and
            # its own description carries the pooling, width and graph file we
            # would be supplying, so there is nothing to add. Without this,
            # configuring any of FastEmbed's ~30 built-in models (bge, e5,
            # MiniLM, gte, ...) fails every embed call.
            _registered.add(model.repo)
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


def _read_repo_json(repo: str, filename: str) -> Optional[dict]:
    """Fetch one small JSON from ``repo``, or ``None`` when it is not there.

    Reads through the Hugging Face hub cache, so a warmed image finds it
    offline. Every failure -- absent file, no network, malformed JSON -- is the
    same answer to the caller: this repository does not tell us.
    """
    try:
        from huggingface_hub import hf_hub_download

        with open(hf_hub_download(repo_id=repo, filename=filename), encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logger.debug("No %s for %s (%s)", filename, repo, exc)
        return None


def _describe_from_repo(repo: str) -> Optional[EmbeddingModel]:
    """Build a spec from a repository's sentence-transformers metadata.

    Args:
        repo: Hugging Face repository id.

    Returns:
        The described model, or ``None`` when the repository carries no
        metadata to read -- leaving the caller to fall back to assumptions.

    Raises:
        RuntimeError: If the model has a Dense projection head. FastEmbed runs
            the transformer and pools it, and nothing else, so the projection
            would be skipped and the vectors come out both the wrong width and
            in a different space. There is no correct way to run it here.
    """
    pooling_config = _read_repo_json(repo, _POOLING_CONFIG)
    if pooling_config is None:
        return None

    kinds = {
        str(module.get("type", "")).rsplit(".", 1)[-1]
        for module in (_read_repo_json(repo, _MODULES_CONFIG) or [])
        if isinstance(module, dict)
    }
    if "Dense" in kinds:
        raise RuntimeError(
            f"Embedding model {repo!r} has a Dense projection layer, which FastEmbed "
            "cannot run: its vectors would be the wrong width and in a different "
            "space than the model was trained to produce. Choose a model without "
            "one, or serve this one over EMBEDDINGS_BASE_URL."
        )

    if pooling_config.get("pooling_mode_cls_token"):
        pooling = "cls"
    elif pooling_config.get("pooling_mode_mean_tokens"):
        pooling = "mean"
    else:
        # max, mean_sqrt_len, weighted-mean: FastEmbed offers none of them, so
        # there is nothing to describe and guessing is what we are avoiding.
        logger.warning(
            "Embedding model %s uses a pooling mode FastEmbed cannot reproduce (%s).",
            repo,
            ", ".join(sorted(k for k, v in pooling_config.items() if v is True)) or "unknown",
        )
        return None

    # ``Normalize`` appears in modules.json only when the model L2-normalises.
    # Its absence is a fact, not missing data: a dot-product model is trained
    # on unnormalised vectors and normalising re-ranks its results.
    normalize = "Normalize" in kinds
    dimension = int(pooling_config.get("word_embedding_dimension") or 0)
    logger.info(
        "Embedding model %s declares %s pooling, normalize=%s, dimension=%s.",
        repo,
        pooling,
        normalize,
        dimension or "unknown",
    )
    return EmbeddingModel(
        name=repo,
        dimension=dimension,
        max_input_tokens=512,
        pooling=pooling,
        normalize=normalize,
        repo=repo,
        onnx_file=_FALLBACK_ONNX_FILE,
    )


def _apply_overrides(spec: EmbeddingModel) -> EmbeddingModel:
    """Let ``EMBEDDINGS_POOLING``/``EMBEDDINGS_NORMALIZE`` win over any source."""
    pooling = getattr(settings, "EMBEDDINGS_POOLING", None)
    normalize = getattr(settings, "EMBEDDINGS_NORMALIZE", None)
    changes = {}
    if isinstance(pooling, str) and pooling.strip().lower() in ("cls", "mean"):
        changes["pooling"] = pooling.strip().lower()
    if isinstance(normalize, bool):
        changes["normalize"] = normalize
    if not changes:
        return spec
    logger.info("Overriding %s from settings: %s", spec.repo, changes)
    return replace(spec, **changes)


def _spec_for(model_name: str) -> EmbeddingModel:
    """Registry entry for ``model_name``, or a best-effort one for a raw repo.

    Args:
        model_name: Configured ``EMBEDDINGS_NAME``.

    Returns:
        The registry entry, else one read from the repository's own
        sentence-transformers metadata, else a last-resort entry assuming the
        standard ONNX layout with mean pooling and ``dimension = 0`` so the
        caller knows to probe for the real width. Settings overrides win over
        all three.
    """
    spec = resolve(model_name)
    if spec is not None:
        return _apply_overrides(spec)

    described = _describe_from_repo(model_name)
    if described is not None:
        return _apply_overrides(described)

    logger.warning(
        "Embedding model %r is not in the registry (known: %s) and its repository "
        "declares no pooling, so %s with L2 normalisation is assumed. If that is "
        "wrong the vectors will be quietly poor rather than fail; set "
        "EMBEDDINGS_POOLING=cls|mean and EMBEDDINGS_NORMALIZE to pin it.",
        model_name,
        ", ".join(known_names()),
        _FALLBACK_POOLING,
    )
    return _apply_overrides(
        EmbeddingModel(
            name=model_name,
            dimension=0,
            max_input_tokens=512,
            pooling=_FALLBACK_POOLING,
            normalize=True,
            repo=model_name,
            onnx_file=_FALLBACK_ONNX_FILE,
        )
    )


def _pad_to_longest_in_batch(model: Any) -> None:
    """Undo a fixed padding width baked into a model's ``tokenizer.json``."""
    # FastEmbed enables padding only when the tokenizer declares none, so a
    # fixed ``length`` survives loading. Shorter inputs are then padded to that
    # width while longer ones keep their own, the batch is ragged, and the ONNX
    # tensor build fails. mpnet ships ``length: 128``; granite does not.
    # Mean pooling masks pad tokens, so the vectors are unaffected.
    tokenizer = getattr(getattr(model, "model", None), "tokenizer", None)
    padding = getattr(tokenizer, "padding", None)
    if not isinstance(padding, dict) or padding.get("length") is None:
        return
    tokenizer.enable_padding(
        direction=padding.get("direction", "right"),
        pad_id=padding.get("pad_id", 0),
        pad_type_id=padding.get("pad_type_id", 0),
        pad_token=padding.get("pad_token", "<pad>"),
        length=None,
        pad_to_multiple_of=padding.get("pad_to_multiple_of"),
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

        _pad_to_longest_in_batch(self.model)
        self.dimension = self.spec.dimension or self._probe_dimension()
        logger.info("Embeddings model ready (dimension=%d)", self.dimension)

    def _probe_dimension(self) -> int:
        """Determine the vector width of a model the registry does not describe."""
        return len(self.embed_query("dimension probe"))

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
