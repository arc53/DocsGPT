"""Download the embedding models a fresh install would otherwise fetch.

Run at image build time so a fresh container does not download on its first
request, and before moving an install onto a host without internet access.
Both the legacy and the current default embedding model are fetched: an
upgraded deployment keeps using mpnet until it runs ``reembed``, while a new
one starts on granite. Each model lands in ``EMBEDDINGS_CACHE_DIR`` together
with its tokenizer, which chunking reads from the same snapshot. tiktoken's
``cl100k_base`` encoding ships inside the package, so there is nothing to warm
for it.

Usage::

    python -m docsgpt.scripts.prefetch_models                 # the defaults
    python -m docsgpt.scripts.prefetch_models granite-311m    # a subset
"""

from __future__ import annotations

import logging
import sys
from typing import List, Optional, Sequence

from docsgpt.vectorstore.model_registry import (
    DEFAULT_LEGACY,
    DEFAULT_NEW_INSTALL,
    known_names,
    resolve,
)

logger = logging.getLogger("prefetch_models")

#: Fetched when no names are given.
DEFAULT_MODELS = (DEFAULT_LEGACY, DEFAULT_NEW_INSTALL)


def prefetch(names: Sequence[str], cache_dir: Optional[str] = None) -> List[str]:
    """Fetch each named model's artifacts.

    Args:
        names: Registry names or aliases.
        cache_dir: FastEmbed cache directory; its default when omitted.

    Returns:
        The repositories actually fetched.

    Raises:
        SystemExit: If a name is not in the registry, since a silent skip at
            build time becomes a download at run time on an offline host.
    """
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    pooling_types = {"cls": PoolingType.CLS, "mean": PoolingType.MEAN}
    fetched: List[str] = []
    for name in names:
        spec = resolve(name)
        if spec is None:
            raise SystemExit(
                f"Unknown embedding model {name!r}. Known: {', '.join(known_names())}"
            )
        if spec.provider != "fastembed":
            logger.info("Skipping %s: served remotely, nothing to cache.", spec.name)
            continue
        logger.info("Fetching %s", spec.repo)
        TextEmbedding.add_custom_model(
            model=spec.repo,
            pooling=pooling_types[spec.pooling],
            normalization=spec.normalize,
            sources=ModelSource(hf=spec.repo),
            dim=spec.dimension,
            model_file=spec.onnx_file,
        )
        kwargs = {"model_name": spec.repo}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        TextEmbedding(**kwargs)
        fetched.append(spec.repo)
    return fetched


def _cache_dir() -> Optional[str]:
    """``EMBEDDINGS_CACHE_DIR`` from the environment, else the directory the app reads.

    The image build sets the variable and copies in only this module's imports,
    so settings are loaded only when the variable is absent.
    """
    import os

    configured = os.environ.get("EMBEDDINGS_CACHE_DIR")
    if configured:
        return configured
    from docsgpt.core.settings import settings

    return settings.EMBEDDINGS_CACHE_DIR or None


def _parse(argv: Optional[Sequence[str]], prog: str, description: str) -> list[str]:
    import argparse

    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "models", nargs="*", help=f"embedding model names or aliases (default: {', '.join(DEFAULT_MODELS)})"
    )
    return parser.parse_args(argv).models or list(DEFAULT_MODELS)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    names = _parse(argv, "prefetch-models", "Download the embedding models and their tokenizers into the model cache.")
    cache_dir = _cache_dir()
    fetched = prefetch(names, cache_dir)
    logger.info("Cached %d model(s) in %s: %s", len(fetched), cache_dir or "FastEmbed's default cache", ", ".join(fetched))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
