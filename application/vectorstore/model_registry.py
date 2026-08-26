"""Canonical description of every embedding model DocsGPT knows how to run.

``EMBEDDINGS_NAME`` used to be a free-form string interpreted in half a dozen
places: a factory dict here, a bundled-model path probe there, a dimension
assertion gated on one model's name, and a hardcoded ``dimension = 768`` on the
remote client. Each of those encoded a different subset of the same facts, and
they drifted.

This module is the single place those facts live. A model is described once and
every consumer -- the local runner, the remote client, the schema bootstrap, the
chunker -- reads the same entry.

Unknown names are not an error: :func:`resolve` returns ``None`` and callers
fall back to treating the name as a Hugging Face repository, which is what a
user configuring an arbitrary model expects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class EmbeddingModel:
    """Everything the application needs to know about one embedding model.

    Attributes:
        name: Canonical ``EMBEDDINGS_NAME`` value.
        dimension: Width of the vectors it produces.
        max_input_tokens: The model's own context window, counted in *its*
            tokenizer. Used to bound what we send it, never to silently
            reshape chunks.
        pooling: ``"cls"`` or ``"mean"`` -- how token vectors become one vector.
        normalize: Whether outputs are L2-normalised to unit length.
        provider: Which runner handles it (``"fastembed"`` or ``"openai"``).
        repo: Hugging Face repository holding weights and tokenizer.
        onnx_file: Path within ``repo`` to the ONNX graph to run.
        aliases: Other spellings of ``name`` accepted from configuration.
    """

    name: str
    dimension: int
    max_input_tokens: int
    pooling: str = "mean"
    normalize: bool = True
    provider: str = "fastembed"
    repo: Optional[str] = None
    onnx_file: Optional[str] = None
    aliases: Tuple[str, ...] = field(default_factory=tuple)


#: The model DocsGPT installed before the granite migration. Kept as the
#: default so an existing deployment that upgrades keeps its index working;
#: new installs are pointed at granite by the setup script and env template.
MPNET = EmbeddingModel(
    name="huggingface_sentence-transformers/all-mpnet-base-v2",
    dimension=768,
    max_input_tokens=384,
    pooling="mean",
    normalize=True,
    repo="sentence-transformers/all-mpnet-base-v2",
    onnx_file="onnx/model.onnx",
    aliases=(
        "huggingface_sentence-transformers-all-mpnet-base-v2",
        "sentence-transformers/all-mpnet-base-v2",
        "all-mpnet-base-v2",
    ),
)

#: Default for new installs: same 768 dimensions as mpnet, an 8x wider
#: effective input, and multilingual retrieval.
GRANITE_311M = EmbeddingModel(
    name="ibm-granite/granite-embedding-311m-multilingual-r2",
    dimension=768,
    max_input_tokens=32768,
    pooling="cls",
    normalize=True,
    repo="ibm-granite/granite-embedding-311m-multilingual-r2",
    onnx_file="onnx/model_quint8_avx2.onnx",
    aliases=("granite-embedding-311m-multilingual-r2", "granite-311m"),
)

#: Smaller granite. Half the vector width, roughly three times the speed.
GRANITE_97M = EmbeddingModel(
    name="ibm-granite/granite-embedding-97m-multilingual-r2",
    dimension=384,
    max_input_tokens=32768,
    pooling="cls",
    normalize=True,
    repo="ibm-granite/granite-embedding-97m-multilingual-r2",
    onnx_file="onnx/model_quint8_avx2.onnx",
    aliases=("granite-embedding-97m-multilingual-r2", "granite-97m"),
)

OPENAI_ADA_002 = EmbeddingModel(
    name="openai_text-embedding-ada-002",
    dimension=1536,
    max_input_tokens=8191,
    pooling="mean",
    normalize=True,
    provider="openai",
    repo=None,
    onnx_file=None,
    aliases=("text-embedding-ada-002",),
)

MODELS: Tuple[EmbeddingModel, ...] = (
    MPNET,
    GRANITE_311M,
    GRANITE_97M,
    OPENAI_ADA_002,
)

#: Fallback vector width when the configured model is unknown -- the width
#: every DocsGPT install has used to date, so an unrecognised model does not
#: silently reshape an existing table.
DEFAULT_EMBEDDING_DIMENSION = 768

#: Name that a fresh install should be configured with.
DEFAULT_NEW_INSTALL = GRANITE_311M.name

#: Name that ``settings.EMBEDDINGS_NAME`` defaults to, i.e. what an existing
#: deployment falls back to when it never pinned one.
DEFAULT_LEGACY = MPNET.name


def _index() -> Dict[str, EmbeddingModel]:
    """Build the lookup table of every accepted spelling."""
    table: Dict[str, EmbeddingModel] = {}
    for model in MODELS:
        for key in (model.name, *model.aliases):
            table[key.lower()] = model
    return table


_LOOKUP = _index()


def resolve(name: Optional[str]) -> Optional[EmbeddingModel]:
    """Return the registry entry for ``name``, or ``None`` when unknown.

    Args:
        name: A configured ``EMBEDDINGS_NAME`` value, in any accepted spelling.

    Returns:
        The matching :class:`EmbeddingModel`, or ``None`` for a name the
        registry does not describe -- which callers treat as a Hugging Face
        repository rather than an error.
    """
    if not name:
        return None
    return _LOOKUP.get(name.strip().lower())


def dimension_for(name: Optional[str]) -> Optional[int]:
    """Vector width for ``name``, or ``None`` when unknown."""
    model = resolve(name)
    return model.dimension if model else None


def max_input_tokens_for(name: Optional[str]) -> Optional[int]:
    """Context window for ``name``, or ``None`` when unknown."""
    model = resolve(name)
    return model.max_input_tokens if model else None


def known_names() -> Tuple[str, ...]:
    """Canonical names of every registered model, for error messages."""
    return tuple(model.name for model in MODELS)
