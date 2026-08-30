"""Download embedding model artifacts into FastEmbed's cache.

Run at image build time so a fresh container does not download a model on its
first ingest, and an air-gapped install works at all. Both the legacy and the
current default are baked: an upgraded deployment keeps using mpnet until it
runs ``reembed``, while a new one starts on granite.

Usage::

    python -m application.scripts.prefetch_models                 # the defaults
    python -m application.scripts.prefetch_models granite-311m    # a subset
"""

from __future__ import annotations

import logging
import sys
from typing import List, Optional, Sequence

from application.vectorstore.model_registry import (
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import os

    names = list(argv) if argv else list(DEFAULT_MODELS)
    fetched = prefetch(names, os.environ.get("EMBEDDINGS_CACHE_DIR"))
    logger.info("Cached %d model(s): %s", len(fetched), ", ".join(fetched))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
