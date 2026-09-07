"""Download the model artifacts a fresh container would otherwise fetch.

Run at image build time so a fresh container does not download on its first
request, and an air-gapped install works at all. Two things are warmed:

* Embedding models, into FastEmbed's cache. Both the legacy and the current
  default are baked: an upgraded deployment keeps using mpnet until it runs
  ``reembed``, while a new one starts on granite.
* tiktoken's ``cl100k_base`` encoding, which token accounting uses on every
  chat. tiktoken caches it under ``TIKTOKEN_CACHE_DIR`` (a temp dir when
  unset), so the image sets that variable and this warms it.

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

#: tiktoken encodings the application loads (``docsgpt.utils.get_encoding``).
TIKTOKEN_ENCODINGS = ("cl100k_base",)


def prefetch_tiktoken(names: Sequence[str] = TIKTOKEN_ENCODINGS) -> List[str]:
    """Warm tiktoken's cache for each encoding in ``names``.

    Returns:
        The encodings fetched.
    """
    import tiktoken

    for name in names:
        logger.info("Fetching tiktoken encoding %s", name)
        tiktoken.get_encoding(name)
    return list(names)


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import os

    names = list(argv) if argv else list(DEFAULT_MODELS)
    fetched = prefetch(names, os.environ.get("EMBEDDINGS_CACHE_DIR"))
    logger.info("Cached %d model(s): %s", len(fetched), ", ".join(fetched))
    encodings = prefetch_tiktoken()
    logger.info("Cached tiktoken encoding(s): %s", ", ".join(encodings))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
