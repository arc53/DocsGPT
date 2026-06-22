"""Additional chunking strategies registered with ``ChunkerCreator``.

Each strategy honours ``max_tokens`` / ``min_tokens`` and reuses the classic
``Chunker``'s tiktoken encoding for token counting, so token budgets stay
consistent across strategies. Selecting a strategy is ingest-time only;
changing it requires a re-ingest (D8). Registered keys: ``recursive``,
``markdown``, ``parent_child``, ``semantic``.
"""

from __future__ import annotations

import logging
import re
from typing import List

from application.parser.chunking import Chunker
from application.parser.chunking_creator import ChunkerCreator
from application.parser.schema.base import Document
from application.utils import get_encoding

logger = logging.getLogger(__name__)


class _BaseStrategyChunker:
    """Shared token helpers for strategy chunkers.

    Mirrors the classic ``Chunker`` constructor so the worker can build any
    strategy with the same kwargs. ``chunking_strategy`` is accepted for
    construction compatibility and not used for dispatch (dispatch lives in
    ``ChunkerCreator``).
    """

    def __init__(
        self,
        chunking_strategy: str = "classic_chunk",
        max_tokens: int = 2000,
        min_tokens: int = 150,
        duplicate_headers: bool = False,
    ):
        self.chunking_strategy = chunking_strategy
        self.max_tokens = max(1, int(max_tokens))
        self.min_tokens = max(0, int(min_tokens))
        self.duplicate_headers = duplicate_headers
        self.encoding = get_encoding()

    def _token_count(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def _split_by_tokens(self, text: str) -> List[str]:
        """Split ``text`` into pieces no larger than ``max_tokens`` tokens."""
        tokens = self.encoding.encode(text)
        pieces = []
        for start in range(0, len(tokens), self.max_tokens):
            chunk_tokens = tokens[start:start + self.max_tokens]
            pieces.append(self.encoding.decode(chunk_tokens))
        return pieces

    def _emit(self, base: Document, part_index: int, text: str) -> Document:
        """Build a child Document carrying token_count and inherited info."""
        return Document(
            text=text,
            doc_id=f"{base.doc_id}-{part_index}" if base.doc_id else None,
            embedding=base.embedding,
            extra_info={
                **(base.extra_info or {}),
                "token_count": self._token_count(text),
            },
        )

    def _merge_to_min(self, pieces: List[str], joiner: str) -> List[str]:
        """Accumulate pieces up to ``max_tokens``, flushing past ``min_tokens``."""
        merged: List[str] = []
        buffer = ""
        for piece in pieces:
            candidate = f"{buffer}{joiner}{piece}" if buffer else piece
            if self._token_count(candidate) <= self.max_tokens:
                buffer = candidate
            else:
                if buffer:
                    merged.append(buffer)
                buffer = piece
            if buffer and self._token_count(buffer) >= self.min_tokens:
                merged.append(buffer)
                buffer = ""
        if buffer:
            merged.append(buffer)
        return merged


class RecursiveChunker(_BaseStrategyChunker):
    """Split on a separator hierarchy, capping at ``max_tokens``.

    Tries paragraph, line, then sentence boundaries before falling back to a
    hard token split, and merges adjacent fragments while their combined size
    stays under ``max_tokens`` so chunks clear ``min_tokens`` where possible.
    """

    _SEPARATORS = ["\n\n", "\n", ". "]

    def _recursive_split(self, text: str, sep_idx: int) -> List[str]:
        if self._token_count(text) <= self.max_tokens:
            return [text] if text.strip() else []
        if sep_idx >= len(self._SEPARATORS):
            return [p for p in self._split_by_tokens(text) if p.strip()]
        sep = self._SEPARATORS[sep_idx]
        parts = text.split(sep)
        out: List[str] = []
        for i, part in enumerate(parts):
            piece = part + sep if i < len(parts) - 1 else part
            if not piece.strip():
                continue
            if self._token_count(piece) <= self.max_tokens:
                out.append(piece)
            else:
                out.extend(self._recursive_split(piece, sep_idx + 1))
        return out

    def _merge(self, fragments: List[str]) -> List[str]:
        """Merge small fragments up to ``max_tokens`` to clear ``min_tokens``."""
        return self._merge_to_min(fragments, "")

    def chunk(self, documents: List[Document]) -> List[Document]:
        processed: List[Document] = []
        for doc in documents:
            fragments = self._recursive_split(doc.text, 0)
            for idx, text in enumerate(self._merge(fragments)):
                processed.append(self._emit(doc, idx, text))
        return processed


class MarkdownChunker(_BaseStrategyChunker):
    """Split on markdown heading boundaries, then token-cap oversized sections.

    Each ``^#{1,6}\\s`` heading starts a new section; sections over
    ``max_tokens`` are further split by token window so no chunk exceeds the
    cap.
    """

    _HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)

    def _sections(self, text: str) -> List[str]:
        boundaries = [m.start() for m in self._HEADING.finditer(text)]
        if not boundaries:
            return [text] if text.strip() else []
        if boundaries[0] != 0:
            boundaries = [0] + boundaries
        sections = []
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
            section = text[start:end]
            if section.strip():
                sections.append(section)
        return sections

    def chunk(self, documents: List[Document]) -> List[Document]:
        processed: List[Document] = []
        for doc in documents:
            part_index = 0
            for section in self._sections(doc.text):
                if self._token_count(section) <= self.max_tokens:
                    processed.append(self._emit(doc, part_index, section))
                    part_index += 1
                else:
                    for piece in self._split_by_tokens(section):
                        if not piece.strip():
                            continue
                        processed.append(self._emit(doc, part_index, piece))
                        part_index += 1
        return processed


class ParentChildChunker(_BaseStrategyChunker):
    """Emit small child chunks for embedding with a larger parent window.

    The document is first split into parent windows of ``max_tokens`` tokens;
    each window is then split into children of ``min_tokens`` (a sane floor of
    50) tokens. Each child stashes its parent window text in
    ``extra_info["parent_text"]`` so retrieval can expand to the parent later.
    The child text is what gets embedded; ``parent_text`` rides through
    ``Document.to_langchain_format`` into vector-store metadata.
    """

    def _child_size(self) -> int:
        size = self.min_tokens if self.min_tokens > 0 else 50
        return min(size, self.max_tokens)

    def chunk(self, documents: List[Document]) -> List[Document]:
        processed: List[Document] = []
        child_size = self._child_size()
        for doc in documents:
            tokens = self.encoding.encode(doc.text)
            part_index = 0
            for p_start in range(0, len(tokens), self.max_tokens):
                parent_tokens = tokens[p_start:p_start + self.max_tokens]
                parent_text = self.encoding.decode(parent_tokens)
                if not parent_text.strip():
                    continue
                for c_start in range(0, len(parent_tokens), child_size):
                    child_tokens = parent_tokens[c_start:c_start + child_size]
                    child_text = self.encoding.decode(child_tokens)
                    if not child_text.strip():
                        continue
                    child = Document(
                        text=child_text,
                        doc_id=(
                            f"{doc.doc_id}-{part_index}" if doc.doc_id else None
                        ),
                        embedding=doc.embedding,
                        extra_info={
                            **(doc.extra_info or {}),
                            "token_count": len(child_tokens),
                            "parent_text": parent_text,
                        },
                    )
                    processed.append(child)
                    part_index += 1
        return processed


class SemanticChunker(_BaseStrategyChunker):
    """Group adjacent sentences by embedding similarity into coherent chunks.

    Sentences are embedded in one batched call and split where the cosine
    distance between consecutive sentences crosses a high percentile, so
    chunk boundaries fall at topic shifts. Chunks are then token-capped at
    ``max_tokens`` and merged up to clear ``min_tokens``. Any failure (too
    few sentences, embedding error, degenerate distances) falls back to
    ``RecursiveChunker`` so ingest never crashes.
    """

    _SENTENCE = re.compile(r"(?<=[.!?])\s+")
    _PERCENTILE = 95.0

    def _split_sentences(self, text: str) -> List[str]:
        return [s for s in (p.strip() for p in self._SENTENCE.split(text)) if s]

    def _fallback(self, documents: List[Document]) -> List[Document]:
        recursive = RecursiveChunker(
            chunking_strategy=self.chunking_strategy,
            max_tokens=self.max_tokens,
            min_tokens=self.min_tokens,
            duplicate_headers=self.duplicate_headers,
        )
        return recursive.chunk(documents)

    def _breakpoints(self, embeddings) -> set:
        """Indices after which a new chunk starts, from high-distance gaps."""
        import numpy as np

        matrix = np.asarray(embeddings, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[0] < 2:
            return set()
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        unit = matrix / norms[:, None]
        sims = np.sum(unit[:-1] * unit[1:], axis=1)
        distances = 1.0 - sims
        if not np.all(np.isfinite(distances)):
            raise ValueError("non-finite semantic distances")
        if float(distances.max()) <= float(distances.min()):
            return set()
        threshold = np.percentile(distances, self._PERCENTILE)
        return {int(i) for i in np.where(distances >= threshold)[0]}

    def _group(self, sentences: List[str], breakpoints: set) -> List[str]:
        groups: List[str] = []
        current: List[str] = []
        for idx, sentence in enumerate(sentences):
            current.append(sentence)
            if idx in breakpoints:
                groups.append(" ".join(current))
                current = []
        if current:
            groups.append(" ".join(current))
        return groups

    def _enforce_tokens(self, groups: List[str]) -> List[str]:
        """Hard-split groups over ``max_tokens`` then merge to clear min."""
        capped: List[str] = []
        for group in groups:
            if self._token_count(group) <= self.max_tokens:
                capped.append(group)
            else:
                capped.extend(p for p in self._split_by_tokens(group) if p.strip())
        return self._merge_to_min(capped, " ")

    def _chunk_text(self, text: str) -> List[str]:
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            raise ValueError("too few sentences for semantic chunking")
        from application.vectorstore.base import EmbeddingsSingleton
        from application.core.settings import settings

        embeddings = EmbeddingsSingleton.get_instance(
            settings.EMBEDDINGS_NAME
        ).embed_documents(sentences)
        breakpoints = self._breakpoints(embeddings)
        groups = self._group(sentences, breakpoints)
        return [g for g in self._enforce_tokens(groups) if g.strip()]

    def chunk(self, documents: List[Document]) -> List[Document]:
        processed: List[Document] = []
        for doc in documents:
            try:
                texts = self._chunk_text(doc.text)
            except Exception as exc:
                logger.warning(
                    "Semantic chunking failed (%s); falling back to recursive.",
                    exc,
                )
                processed.extend(self._fallback([doc]))
                continue
            for idx, text in enumerate(texts):
                processed.append(self._emit(doc, idx, text))
        return processed


ChunkerCreator.register("recursive", RecursiveChunker)
ChunkerCreator.register("markdown", MarkdownChunker)
ChunkerCreator.register("parent_child", ParentChildChunker)
ChunkerCreator.register("semantic", SemanticChunker)

# Reuse the classic Chunker reference so this module can be the single import
# that pulls every strategy into the registry.
__all__ = [
    "RecursiveChunker",
    "MarkdownChunker",
    "ParentChildChunker",
    "SemanticChunker",
    "Chunker",
]
