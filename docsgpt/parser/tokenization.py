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

Tokenizers are fed bounded windows, never a whole document (#3130). The
per-token data an encode materialises -- ids, offsets, a Python tuple per
offset -- costs about 180-430 bytes per character, so one 80 MiB Chinese text
file peaked a worker at 10.3 GiB. :class:`TokenCounter` walks text longer than
``_WINDOW_CHARS`` window by window, and no ``encode``, ``encode_ordinary`` or
``decode_with_offsets`` call sees more than ``2 * _WINDOW_CHARS`` characters.
Windows end where pre-tokenizers already break (after a newline, before a
space), so counts of ordinary prose stay exact. In a document longer than one
window, chunk boundaries after the first seam can shift by a few tokens,
because each segment re-encodes from a piece boundary; every piece still stays
within its budget.
"""

from __future__ import annotations

import logging
import threading
import unicodedata
from typing import Iterator, List, Optional, Tuple

from docsgpt.core.settings import settings
from docsgpt.utils import get_encoding
from docsgpt.vectorstore.model_registry import resolve

logger = logging.getLogger(__name__)

_cache: dict = {}
_cache_lock = threading.Lock()

# Characters handed to one tokenizer call, before the split carry (which can
# double it). At ~195 bytes per character this is about 12 MiB transient per
# encode. Read at call time, so tests can shrink it to exercise many seams.
_WINDOW_CHARS = 65_536

# Categories that attach to the preceding character: combining marks,
# enclosing marks, and format controls such as ZWJ. A cut in front of one
# would separate it from its base.
_GLUE_CATEGORIES = frozenset({"Mn", "Me", "Cf"})


def _is_glue(char: str) -> bool:
    """Whether ``char`` must stay with the character before it."""
    return 0xD800 <= ord(char) <= 0xDFFF or unicodedata.category(char) in _GLUE_CATEGORIES


def _window_cut(text: str, start: int, size: int) -> int:
    """Pick where the window starting at ``start`` ends.

    The cut prefers places every supported pre-tokenizer already breaks at, so
    tokenizing the two sides separately gives the tokens a one-shot encode
    would.

    Args:
        text: Source text; it must extend past ``start + size``.
        start: Index the window starts at.
        size: Maximum window length.

    Returns:
        The exclusive end of the window, in ``(start + size // 2, start + size]``.
    """
    lo, hi = start + size // 2, start + size

    # 1. After a newline that precedes text. cl100k's ``\s*[\r\n]+`` and the
    #    whitespace pre-tokenizers end a pretoken there. A newline followed by
    #    more whitespace sits inside one run, so look for an earlier one.
    i = text.rfind("\n", lo, hi)
    while i != -1 and text[i + 1].isspace():
        i = text.rfind("\n", lo, i)
    if i != -1:
        return i + 1

    # 2. Before a space that follows text. cl100k (`` ?\p{L}+``) and Metaspace
    #    attach a leading space to the next word, so cutting after the space
    #    would split that token in two.
    i = text.rfind(" ", lo + 1, hi)
    while i != -1 and text[i - 1].isspace():
        i = text.rfind(" ", lo + 1, i)
    if i != -1:
        return i

    # 3. Hard cut, stepped back so it never separates a mark from its base. A
    #    back half made only of glue has no clean cut, so take ``hi``.
    p = hi
    while p > lo and _is_glue(text[p]):
        p -= 1
    return p if p > lo else hi


def _text_windows(text: str, size: int) -> Iterator[Tuple[int, int]]:
    """Yield contiguous ``(start, end)`` character windows tiling ``text``.

    Args:
        text: Source text.
        size: Maximum window length.

    Yields:
        Windows of at most ``size`` characters, each but the last covering
        more than ``size // 2``. A text within ``size`` is a single window.
    """
    start = 0
    while len(text) - start > size:
        end = _window_cut(text, start, size)
        yield start, end
        start = end
    yield start, len(text)


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
        """Number of tokens ``text`` occupies, counted window by window.

        Prose windows end where the tokenizer breaks anyway, so the sum equals
        a one-shot count. A hard cut through unbroken text can add a few
        tokens per seam: inside a word longer than WordPiece's limit, one
        ``[UNK]`` becomes ordinary wordpieces on both sides.

        Args:
            text: Source text.

        Returns:
            The token count; 0 for an empty ``text``.
        """
        if not text:
            return 0
        size = _WINDOW_CHARS
        if len(text) <= size:
            return self._count_one(text)
        return sum(self._count_one(text[start:end]) for start, end in _text_windows(text, size))

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
        if not text:
            return []
        rest = max(1, max_tokens)
        first = max(1, first_max_tokens if first_max_tokens is not None else rest)
        size = _WINDOW_CHARS
        if len(text) <= size:
            return self._split_one(text, first, rest)

        # Split a segment at a time and keep every piece but the last, which
        # may have been cut short by the window rather than the budget; it is
        # carried into the next segment. Re-encoding from a piece boundary can
        # move later boundaries by a token against a one-shot split (the
        # boundary can fall inside a cl100k CJK pretoken or a WordPiece ``##``
        # run), but every piece is still a split output, so within budget.
        pieces: List[str] = []
        seg_start = 0
        for _, end in _text_windows(text, size):
            out = self._split_one(text[seg_start:end], first if not pieces else rest, rest)
            for piece in out[:-1]:
                pieces.append(piece)
                seg_start += len(piece)
            # A carry longer than a window (a zero-token blank run, a budget no
            # window fills) is emitted as it stands. Left to grow, the next
            # encode would approach the whole text and the work go quadratic.
            if end - seg_start > size:
                pieces.append(text[seg_start:end])
                seg_start = end
        if seg_start < len(text):
            pieces.append(text[seg_start:])
        return pieces

    def _count_one(self, text: str) -> int:
        """Count a non-empty ``text`` of at most ``2 * _WINDOW_CHARS`` in one encode."""
        raise NotImplementedError

    def _split_one(self, text: str, first: int, rest: int) -> List[str]:
        """Split a non-empty ``text`` of at most ``2 * _WINDOW_CHARS`` in one encode.

        Args:
            text: Source segment.
            first: Budget for the first piece, already clamped to at least 1.
            rest: Budget for every later piece, already clamped to at least 1.

        Returns:
            Pieces that reassemble ``text`` exactly.
        """
        raise NotImplementedError


def split_to_token_limit(
    counter: TokenCounter,
    text: str,
    max_tokens: int,
    first_max_tokens: Optional[int] = None,
) -> List[str]:
    """Split text losslessly and verify every piece against the token limit.

    A tokenizer may count a long unknown-token span by its weighted character
    length while exposing only one offset for that span. Its normal
    offset-window splitter can therefore still return an oversized piece.
    Recheck every result and bisect any piece for which the tokenizer cannot
    make progress.

    Args:
        counter: Token counter used by the embedding model.
        text: Original text to split without modification.
        max_tokens: Maximum token count for every returned piece.
        first_max_tokens: Optional smaller budget for the first piece, used
            when a duplicated header consumes part of its allowance.

    Returns:
        Consecutive pieces that reassemble to ``text`` exactly and each fit
        within ``max_tokens``.
    """
    if not text:
        return []

    limit = max(1, int(max_tokens))
    first_limit = max(
        1,
        int(first_max_tokens) if first_max_tokens is not None else limit,
    )
    if first_limit != limit:
        pieces = counter.split(text, limit, first_max_tokens=first_limit)
        if not pieces or "".join(pieces) != text:
            pieces = [text]
        bounded: List[str] = []
        for index, piece in enumerate(pieces):
            piece_limit = first_limit if index == 0 else limit
            bounded.extend(split_to_token_limit(counter, piece, piece_limit))
        return bounded

    bounded: List[str] = []
    pending = [text]
    while pending:
        piece = pending.pop()
        if counter.count(piece) <= limit:
            bounded.append(piece)
            continue

        candidates = [candidate for candidate in counter.split(piece, limit) if candidate]
        made_progress = (
            len(candidates) > 1
            and "".join(candidates) == piece
            and all(len(candidate) < len(piece) for candidate in candidates)
        )
        if not made_progress:
            if len(piece) <= 1:
                raise ValueError("token counter cannot split an over-limit character")
            midpoint = len(piece) // 2
            candidates = [piece[:midpoint], piece[midpoint:]]

        # The worklist is LIFO; reverse children to retain source order.
        pending.extend(reversed(candidates))

    return bounded


class TiktokenCounter(TokenCounter):
    """cl100k counter -- the historical behaviour, and the fallback."""

    name = "cl100k_base"

    def __init__(self) -> None:
        self._encoding = get_encoding()

    def _count_one(self, text: str) -> int:
        return len(self._encoding.encode_ordinary(text))

    def _split_one(self, text: str, first: int, rest: int) -> List[str]:
        tokens = self._encoding.encode_ordinary(text)
        if len(tokens) <= first:
            return [text]

        # Cut the original string at the character offsets the tokenizer
        # reports, the way :class:`HuggingFaceCounter` does. Decoding each
        # window on its own instead splits any multi-byte character that
        # straddles a boundary across two byte sequences, and each half decodes
        # to U+FFFD -- roughly one boundary in five on CJK text, silently
        # destroying a character per cut.
        offsets = self._encoding.decode_with_offsets(tokens)[1]
        end_of_text = len(text)
        pieces: List[str] = []
        cursor = 0
        for _, end in _windows(len(tokens), first, rest):
            # Offsets index into the decoded string. ``encode_ordinary``
            # round-trips for anything cl100k can represent, so it is ``text``;
            # clamping keeps the cuts in range if it ever is not, and slicing
            # ``text`` monotonically keeps the pieces reassembling exactly
            # either way.
            end_char = end_of_text if end >= len(offsets) else min(offsets[end], end_of_text)
            if end_char <= cursor:
                continue
            pieces.append(text[cursor:end_char])
            cursor = end_char
        if cursor < end_of_text:
            if pieces:
                pieces[-1] = pieces[-1] + text[cursor:]
            else:
                pieces.append(text[cursor:])
        return pieces


class HuggingFaceCounter(TokenCounter):
    """Counts in a Hugging Face tokenizer, slicing by character offsets."""

    def __init__(self, tokenizer, name: str) -> None:
        self._tokenizer = tokenizer
        self.name = name

    def _encode(self, text: str):
        return self._tokenizer.encode(text, add_special_tokens=False)

    @staticmethod
    def _weigh(encoding) -> int:
        """Tokens an encoding costs, charging collapsed runs by their span.

        Args:
            encoding: A ``tokenizers`` encoding, or anything with ``ids`` and
                ``offsets``.

        Returns:
            The weighted token count.
        """
        if not encoding.offsets:
            return len(encoding.ids)
        return sum(_token_weight(start, end) for start, end in encoding.offsets)

    def _count_one(self, text: str) -> int:
        return self._weigh(self._encode(text))

    def _split_one(self, text: str, first: int, rest: int) -> List[str]:
        # One encode serves both the weight check and the offsets. Counting
        # separately used to hold a second encoding of the same text alive.
        encoding = self._encode(text)
        if self._weigh(encoding) <= first:
            return [text]
        offsets = encoding.offsets

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


def _tokenizer_file(repo: str) -> str:
    """Path to ``repo``'s ``tokenizer.json``, from the embedding model cache when present.

    FastEmbed's snapshot of the repository in ``EMBEDDINGS_CACHE_DIR`` already
    holds the file, so a warmed cache answers without touching the network.
    ``hf_hub_download`` would otherwise revalidate the revision with a HEAD
    request on every process start, and stall for the etag timeout on a host
    that cannot reach huggingface.co.
    """
    from huggingface_hub import hf_hub_download

    cache_dir = settings.EMBEDDINGS_CACHE_DIR or None
    try:
        return hf_hub_download(repo, "tokenizer.json", local_files_only=True, cache_dir=cache_dir)
    except Exception:  # noqa: BLE001 -- not cached: fetch it
        return hf_hub_download(repo, "tokenizer.json", cache_dir=cache_dir)


def _load_hf_counter(repo: str) -> Optional[HuggingFaceCounter]:
    """Load ``repo``'s tokenizer, or ``None`` if it is not reachable."""
    try:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(_tokenizer_file(repo))
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
    name = embeddings_name or settings.EMBEDDINGS_NAME
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


def count_tokens_windowed(text: str) -> int:
    """Count ``text`` in cl100k tokens, window by window.

    For ingest's whole-file counts: the per-file ``token_count`` in
    :mod:`docsgpt.parser.file.bulk` and the markdown parser's chunk check.
    They always counted cl100k and still do, but one encode of a whole file
    is the per-character memory cost #3130 removes, so they go through
    :class:`TiktokenCounter`'s bounded windows instead.
    :func:`docsgpt.utils.num_tokens_from_string` stays one-shot for its other
    callers, which take offsets from a single encode.

    A counter is built per call rather than cached here; ``get_encoding`` is
    cached, so construction is cheap.

    Args:
        text: Text of any length.

    Returns:
        The token count. It equals a one-shot count on prose, and may differ
        from one by about a token at each hard-cut seam.
    """
    return TiktokenCounter().count(text)


def reset_cache() -> None:
    """Drop cached counters. For tests and for a settings change at runtime."""
    with _cache_lock:
        _cache.clear()
