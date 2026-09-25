"""Search inside chat attachments.

Two rankers share one chunking, so a hit always carries the same character
offset whichever ranker found it:

* keyword (BM25) over the attachment's stored text, available the moment the
  file is parsed — nothing to wait for;
* semantic, over the vectors the background indexer writes to the
  attachment's own hidden source (``attachment_index``), used once that
  attachment's ``metadata.index.status`` is ``done``.

``attachments_search`` ranks indexed files semantically and the rest by
keyword, and interleaves the two so a file still indexing is never invisible.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

CHUNK_CHARS = 2000
CHUNK_OVERLAP = 200

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Chunk:
    """A window of one attachment's text."""

    attachment_id: str
    offset: int
    text: str


@dataclass
class Hit:
    """One search result."""

    attachment_id: str
    offset: int
    text: str
    score: float
    ranker: str


def chunk_text(attachment_id: str, content: str) -> List[Chunk]:
    """Split ``content`` into overlapping windows that end on whitespace.

    Args:
        attachment_id: Stamped on every chunk.
        content: The attachment's stored text.

    Returns:
        Chunks in document order, each with its start offset in ``content``.
    """
    chunks: List[Chunk] = []
    if not content:
        return chunks
    length = len(content)
    start = 0
    while start < length:
        end = min(start + CHUNK_CHARS, length)
        if end < length:
            # Back off to the last whitespace in the final fifth of the window
            # so a word is never split across two chunks.
            cut = content.rfind(" ", start + CHUNK_CHARS * 4 // 5, end)
            newline = content.rfind("\n", start + CHUNK_CHARS * 4 // 5, end)
            cut = max(cut, newline)
            if cut > start:
                end = cut
        text = content[start:end]
        if text.strip():
            chunks.append(Chunk(attachment_id=attachment_id, offset=start, text=text))
        if end >= length:
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _terms(text: str) -> List[str]:
    return [t.lower() for t in _WORD.findall(text or "")]


def keyword_search(chunks: Sequence[Chunk], query: str, k: int) -> List[Hit]:
    """Rank ``chunks`` against ``query`` with BM25.

    Args:
        chunks: Candidate chunks, possibly from several attachments.
        query: The model's search query.
        k: Most hits to return.

    Returns:
        Up to ``k`` hits with a positive score, best first.
    """
    query_terms = set(_terms(query))
    if not chunks or not query_terms or k <= 0:
        return []
    k1, b = 1.5, 0.75
    tokenized = [_terms(c.text) for c in chunks]
    lengths = [len(t) for t in tokenized]
    avg_len = (sum(lengths) / len(lengths)) or 1.0
    doc_freq: Counter = Counter()
    for terms in tokenized:
        doc_freq.update(set(terms) & query_terms)
    n = len(chunks)
    scored: List[Hit] = []
    for chunk, terms, length in zip(chunks, tokenized, lengths):
        if not terms:
            continue
        counts = Counter(t for t in terms if t in query_terms)
        if not counts:
            continue
        score = 0.0
        for term, freq in counts.items():
            df = doc_freq[term]
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * length / avg_len))
        scored.append(
            Hit(
                attachment_id=chunk.attachment_id,
                offset=chunk.offset,
                text=chunk.text,
                score=score,
                ranker="keyword",
            )
        )
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[:k]


def semantic_search(
    source_ids: Dict[str, str],
    query: str,
    k: int,
    store_factory: Optional[Callable[[str], object]] = None,
) -> List[Hit]:
    """Search each indexed attachment's vectors and merge the results.

    Args:
        source_ids: ``{attachment_id: source_id}`` for indexed attachments.
        query: The model's search query.
        k: Most hits to return overall.
        store_factory: Builds the vector store for a source id; defaults to
            the configured backend.

    Returns:
        Up to ``k`` hits, best first. A store that fails to answer is skipped
        (logged), so one broken index never hides the others.
    """
    if not source_ids or k <= 0:
        return []
    if store_factory is None:
        from docsgpt.core.settings import settings
        from docsgpt.vectorstore.vector_creator import VectorCreator

        def store_factory(source_id: str):
            return VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
            )

    hits: List[Hit] = []
    for attachment_id, source_id in source_ids.items():
        try:
            store = store_factory(source_id)
            results = store.search(query, k=k)
        except Exception:
            logger.warning(
                "attachment semantic search failed",
                extra={"attachment_id": attachment_id, "source_id": source_id},
                exc_info=True,
            )
            continue
        for rank, doc in enumerate(results or []):
            metadata = getattr(doc, "metadata", None) or {}
            text = getattr(doc, "page_content", None) or str(doc)
            offset = metadata.get("offset")
            hits.append(
                Hit(
                    attachment_id=attachment_id,
                    offset=int(offset) if isinstance(offset, (int, float)) else 0,
                    text=text,
                    # Stores disagree on score scales; rank within each store
                    # is the one comparable signal, so merge on it.
                    score=1.0 / (rank + 1),
                    ranker="semantic",
                )
            )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def interleave(*ranked: Iterable[Hit], k: int) -> List[Hit]:
    """Round-robin merge of ranked lists, dropping repeats of the same chunk."""
    lists = [list(r) for r in ranked]
    merged: List[Hit] = []
    seen = set()
    index = 0
    while len(merged) < k and any(index < len(lst) for lst in lists):
        for lst in lists:
            if index < len(lst):
                hit = lst[index]
                key = (hit.attachment_id, hit.offset)
                if key not in seen:
                    seen.add(key)
                    merged.append(hit)
                    if len(merged) >= k:
                        break
        index += 1
    return merged
