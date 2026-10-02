"""Shared chunk-label derivation for retrievers."""

from __future__ import annotations

import os
from typing import Any, Dict


def labels_from_metadata(
    metadata: Dict[str, Any], text: str, fallback_source: str
) -> Dict[str, str]:
    """Derive a chunk's citation labels from its metadata.

    Falls back to the chunk text for the title and to ``fallback_source`` (the
    vectorstore/source id) when metadata carries no source. Used by both
    ClassicRAG and GraphRAG so citation labels stay identical across retrievers.

    Besides ``title``/``source``/``filename`` the result carries the chunk's
    identity, so a citation can find the chunk again: ``source_id`` (the source
    it belongs to) and ``chunk_key`` (see :func:`chunk_key`). Retrieval drops
    the raw metadata after this point, so anything a citation needs has to be
    handed on here.

    Args:
        metadata: The stored chunk's metadata.
        text: The chunk's text.
        fallback_source: The id of the store the chunk was retrieved from.

    Returns:
        dict: ``title``, ``source``, ``filename``, ``source_id``, ``chunk_key``.
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
    return {
        "title": title,
        "source": source,
        "filename": filename,
        "source_id": normalize_source_id(metadata.get("source_id") or fallback_source),
        "chunk_key": chunk_key(text),
    }


def chunk_key(text: Any) -> str:
    """Content key of a chunk: the MD5 of its UTF-8 text, as Postgres ``md5(text)``.

    The store's row id changes on every re-ingest, so a citation saved with a
    conversation would go stale the first time the source is rebuilt. The text
    does not, and Postgres can match the key with its own ``md5()`` without a
    schema change.

    Args:
        text: The chunk's text; ``None`` hashes as the empty string.

    Returns:
        str: 32 lowercase hex characters.
    """
    from docsgpt.utils import get_hash

    return get_hash(str(text or ""))


def normalize_source_id(source_id: Any) -> str:
    """Strip the legacy index prefix a vectorstore id may still carry.

    Args:
        source_id: A source id, possibly ``docsgpt/indexes/<id>/``.

    Returns:
        str: The bare id, or ``""``.
    """
    return str(source_id or "").replace("docsgpt/indexes/", "").rstrip("/")
