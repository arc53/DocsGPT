"""Shared chunk-label derivation for retrievers."""

from __future__ import annotations

import os
from typing import Any, Dict


def labels_from_metadata(
    metadata: Dict[str, Any], text: str, fallback_source: str
) -> Dict[str, str]:
    """Derive ``title``/``source``/``filename`` from a chunk's metadata.

    Falls back to the chunk text for the title and to ``fallback_source`` (the
    vectorstore/source id) when metadata carries no source. Used by both
    ClassicRAG and GraphRAG so citation labels stay identical across retrievers.
    """
    metadata = metadata or {}

    title = metadata.get("title", metadata.get("post_title", text))
    if not isinstance(title, str):
        title = str(title)
    title = title.split("/")[-1]

    filename = (
        metadata.get("filename")
        or metadata.get("file_name")
        or metadata.get("source")
    )
    if isinstance(filename, str):
        filename = os.path.basename(filename) or filename
    else:
        filename = title
    if not filename:
        filename = title

    source = metadata.get("source") or fallback_source
    return {"title": title, "source": source, "filename": filename}
