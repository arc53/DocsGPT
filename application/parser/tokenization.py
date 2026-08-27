"""Counting and splitting text in the embedding model's own tokenizer.

Chunk sizes only mean something in the units the embedding server counts. The
chunker used to count cl100k (tiktoken) while the server counted whatever its
model used, so ``max_tokens`` was a value in one unit compared against a limit
in another. Every recalibration of that number was really an attempt to guess
the conversion factor.

This module removes the conversion. :func:`get_token_counter` returns a counter
backed by the configured embedding model's tokenizer, falling back to cl100k
when that tokenizer cannot be loaded -- an offline install, or a model the
registry does not describe.

Splitting never round-trips through ``decode``. Byte-level BPE decodes
losslessly, but WordPiece tokenizers do not: all-mpnet-base-v2 lowercases, so
decoding ``"Hello World"`` yields ``"hello world"`` and would silently rewrite
every stored document. Counters therefore cut the *original* string at
character offsets the tokenizer reports.
"""

from __future__ import annotations

import logging
import threading
from typing import Iterator, List, Optional, Tuple

from application.core.settings import settings
from application.utils import get_encoding
from application.vectorstore.model_registry import resolve

logger = logging.getLogger(__name__)

_cache: dict = {}
_cache_lock = threading.Lock()


def _windows(total: int, first: int, rest: int) -> Iterator[Tuple[int, int]]:
    """Yield ``(start, end)`` token windows, the first sized independently.

    A header consumes part of the first chunk's budget but none of the rest,
    so the first window is often smaller than those that follow.
    """
    start = 0
    budget = max(1, first)
    while start < total:
        end = min(start + budget, total)
        yield start, end
        start = end
        budget = max(1, rest)


# A token spanning more characters than this collapsed a run the tokenizer
# could not break up: WordPiece emits a single ``[UNK]`` for any word longer
# than ``max_input_chars_per_word``. Charging that once makes a base64 blob or
# a minified bundle look tiny, so nothing splits it and an oversized chunk
# reaches the embedding server. Real tokens are a few characters, so prose
# never reaches this bound.
_MAX_CHARS_PER_TOKEN = 16


def _token_weight(start: int, end: int) -> int:
    """Tokens a span costs, charging a collapsed run by its length."""
    span = end - start
    return max(1, -(-span // _MAX_CHARS_PER_TOKEN))


def _cap_piece_chars(pieces: List[str], first: int, rest: int) -> List[str]:
    """Cut any piece holding more characters than its budget can cover."""
    capped: List[str] = []
    budget = first
    for piece in pieces:
        limit = max(1, budget * _MAX_CHARS_PER_TOKEN)
        while len(piece) > limit:
            capped.append(piece[:limit])
            piece = piece[limit:]
            budget = rest
            limit = max(1, budget * _MAX_CHARS_PER_TOKEN)
        capped.append(piece)
        budget = rest
    return capped


class TokenCounter:
    """Counts and splits text in one tokenizer's units.

    Attributes:
        name: Human-readable identifier of the underlying tokenizer, for logs.
    """

    name = "unknown"

    def count(self, text: str) -> int:
        """Number of tokens ``text`` occupies."""
        raise NotImplementedError

    def split(
        self, text: str, max_tokens: int, first_max_tokens: Optional[int] = None
    ) -> List[str]:
        """Cut ``text`` into consecutive pieces of at most ``max_tokens``.

        The concatenation of the returned pieces equals ``text`` exactly.

        Args:
            text: Source text.
            max_tokens: Token budget per piece; values below 1 are treated as 1.
            first_max_tokens: Budget for the first piece only, when it must
                leave room for a header. Defaults to ``max_tokens``.

        Returns:
            The pieces, in order. An empty ``text`` yields an empty list.
        """
        raise NotImplementedError


class TiktokenCounter(TokenCounter):
    """cl100k counter -- the historical behaviour, and the fallback."""

    name = "cl100k_base"

    def __init__(self) -> None:
        self._encoding = get_encoding()

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoding.encode_ordinary(text))

    def split(
        self, text: str, max_tokens: int, first_max_tokens: Optional[int] = None
    ) -> List[str]:
        if not text:
            return []
        rest = max(1, max_tokens)
        first = max(1, first_max_tokens if first_max_tokens is not None else rest)
        tokens = self._encoding.encode_ordinary(text)
        if len(tokens) <= first:
            return [text]
        return [
            self._encoding.decode(tokens[start:end])
            for start, end in _windows(len(tokens), first, rest)
        ]


class HuggingFaceCounter(TokenCounter):
    """Counts in a Hugging Face tokenizer, slicing by character offsets."""

    def __init__(self, tokenizer, name: str) -> None:
        self._tokenizer = tokenizer
        self.name = name

    def _encode(self, text: str):
        return self._tokenizer.encode(text, add_special_tokens=False)

    def count(self, text: str) -> int:
        if not text:
            return 0
        encoding = self._encode(text)
        if not encoding.offsets:
            return len(encoding.ids)
        return sum(_token_weight(start, end) for start, end in encoding.offsets)

    def split(
        self, text: str, max_tokens: int, first_max_tokens: Optional[int] = None
    ) -> List[str]:
        if not text:
            return []
        rest = max(1, max_tokens)
        first = max(1, first_max_tokens if first_max_tokens is not None else rest)
        offsets = self._encode(text).offsets
        if self.count(text) <= first:
            return [text]

        pieces: List[str] = []
        cursor = 0
        for start_token, end_token in _windows(len(offsets), first, rest):
            window = offsets[start_token:end_token]
            # Some tokenizers emit (0, 0) for specials or normalised-away
            # characters; those carry no span to cut on.
            spans = [end for _, end in window if end > cursor]
            if not spans:
                continue
            end_char = max(spans)
            pieces.append(text[cursor:end_char])
            cursor = end_char
        if cursor < len(text):
            # Trailing characters the tokenizer dropped (e.g. whitespace) belong
            # to the final piece, so no input is lost.
            if pieces:
                pieces[-1] = pieces[-1] + text[cursor:]
            else:
                pieces.append(text[cursor:])
        return _cap_piece_chars(pieces, first, rest)


def _load_hf_counter(repo: str) -> Optional[HuggingFaceCounter]:
    """Load ``repo``'s tokenizer, or ``None`` if it is not reachable."""
    try:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_pretrained(repo)
        # Repos ship padding and truncation defaults meant for inference
        # batches. Left on, every count returns the padded width (128 for
        # mpnet) and the offsets carry (0, 0) entries for the padding, so both
        # counting and slicing are wrong.
        tokenizer.no_padding()
        tokenizer.no_truncation()
        return HuggingFaceCounter(tokenizer, repo)
    except Exception as exc:  # noqa: BLE001 -- chunking must never hard-fail here
        logger.warning(
            "Could not load the tokenizer for %s (%s); counting chunk sizes in "
            "cl100k instead. Chunk sizes will be approximate for this model.",
            repo,
            exc,
        )
        return None


def get_token_counter(embeddings_name: Optional[str] = None) -> TokenCounter:
    """Return the counter for ``embeddings_name``, cached per process.

    Args:
        embeddings_name: Model name; defaults to ``settings.EMBEDDINGS_NAME``.

    Returns:
        A :class:`HuggingFaceCounter` for a model whose tokenizer could be
        loaded, else a :class:`TiktokenCounter`.
    """
    name = embeddings_name or getattr(settings, "EMBEDDINGS_NAME", None)
    key = name or "__default__"
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    spec = resolve(name)
    repo = spec.repo if spec else name
    counter: TokenCounter
    if repo and (spec is None or spec.provider == "fastembed"):
        counter = _load_hf_counter(repo) or TiktokenCounter()
    else:
        counter = TiktokenCounter()

    with _cache_lock:
        _cache[key] = counter
    logger.info("Chunking will count tokens with %s", counter.name)
    return counter


def reset_cache() -> None:
    """Drop cached counters. For tests and for a settings change at runtime."""
    with _cache_lock:
        _cache.clear()
