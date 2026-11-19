"""Fuzz token-bounded splitting and the chunkers built on it.

Every ingested document is cut by ``split_to_token_limit`` and one of the
chunking strategies before it is embedded, so these run on arbitrary
extracted text. Tokens are counted in cl100k, the counter's fallback, so the
harness needs no model download.

Invariants checked on every input:

* ``split_to_token_limit`` is lossless (its pieces concatenate to the input)
  and every piece fits its budget, including a smaller first-piece budget; it
  may refuse only a budget below the four tokens one character can take;
* the classic ``Chunker``, ``MarkdownChunker`` and ``RecursiveChunker`` emit
  chunks within ``max_tokens`` whose recorded ``token_count`` is accurate;
* the classic chunker without duplicated headers returns the text exactly,
  and the other two (without overlap) drop or reorder no non-whitespace text.
"""

from __future__ import annotations

import logging
import sys

import atheris

with atheris.instrument_imports(include=["docsgpt"]):
    from docsgpt.parser.chunking import Chunker
    from docsgpt.parser.chunking_strategies import MarkdownChunker, RecursiveChunker
    from docsgpt.parser.schema.base import Document
    from docsgpt.parser.tokenization import TiktokenCounter, split_to_token_limit

# The chunkers log every header they demote; that is expected here, thousands of times a second.
logging.disable(logging.CRITICAL)
_COUNTER = TiktokenCounter()
# A code point is at most four UTF-8 bytes, so at most four cl100k tokens.
_MAX_CHAR_TOKENS = 4
_FRAGMENTS = [
    "# Title\n", "## Sub\n", "###### deep\n", "#no-space\n", "\n\n", "\n", ". ", " ", "\t", "\r\n",
    "word ", "longwordwithoutbreaks", "1234567890", "é", "\U0001f469‍\U0001f4bb", " ",
    "中文字符", "<|endoftext|>", "```code```", "| a | b |\n",
]


def _text(fdp: atheris.FuzzedDataProvider) -> str:
    """Document text mixing markdown and separator fragments with raw input."""
    pieces = []
    for _ in range(fdp.ConsumeIntInRange(0, 24)):
        if fdp.ConsumeIntInRange(0, 2) == 0:
            pieces.append(fdp.ConsumeUnicodeNoSurrogates(48))
        else:
            pieces.append(fdp.PickValueInList(_FRAGMENTS) * fdp.ConsumeIntInRange(1, 4))
    return "".join(pieces)


def _squash(text: str) -> str:
    """``text`` without whitespace, for comparing content across chunk boundaries."""
    return "".join(text.split())


def _check_chunks(chunks: list[Document], max_tokens: int) -> None:
    """Every chunk fits the budget and carries its real token count."""
    for chunk in chunks:
        count = _COUNTER.count(chunk.text)
        assert count <= max_tokens, (max_tokens, count, chunk.text)
        assert chunk.extra_info["token_count"] == count, (chunk.extra_info, count)


def _check_split(fdp: atheris.FuzzedDataProvider, text: str) -> None:
    """``split_to_token_limit`` is lossless and bounded for any budgets."""
    max_tokens = fdp.ConsumeIntInRange(1, 64)
    first_max = fdp.ConsumeIntInRange(1, max_tokens) if fdp.ConsumeBool() else None
    try:
        pieces = split_to_token_limit(_COUNTER, text, max_tokens, first_max_tokens=first_max)
    except ValueError:
        assert min(max_tokens, first_max or max_tokens) < _MAX_CHAR_TOKENS, (max_tokens, first_max, text)
        return
    assert "".join(pieces) == text, (text, pieces)
    for index, piece in enumerate(pieces):
        budget = first_max if index == 0 and first_max is not None else max_tokens
        assert piece and _COUNTER.count(piece) <= budget, (budget, piece)


def TestOneInput(data: bytes) -> None:
    """Split one generated document every way and check the pieces."""
    fdp = atheris.FuzzedDataProvider(data)
    max_tokens = fdp.ConsumeIntInRange(_MAX_CHAR_TOKENS, 64)
    min_tokens = fdp.ConsumeIntInRange(0, max_tokens)
    overlap = fdp.ConsumeIntInRange(0, max_tokens) if fdp.ConsumeBool() else 0
    duplicate_headers = fdp.ConsumeBool()
    text = _text(fdp)
    _check_split(fdp, text)

    classic = Chunker(max_tokens=max_tokens, min_tokens=min_tokens, duplicate_headers=duplicate_headers)
    classic.counter = _COUNTER
    chunks = classic.chunk([Document(text=text, doc_id="doc", extra_info={"source": "fuzz"})])
    _check_chunks(chunks, max_tokens)
    if not duplicate_headers:
        assert "".join(chunk.text for chunk in chunks) == text, (text, [chunk.text for chunk in chunks])

    for chunker_class in (MarkdownChunker, RecursiveChunker):
        chunker = chunker_class(max_tokens=max_tokens, min_tokens=min_tokens, chunk_overlap=overlap)
        chunker.counter = _COUNTER
        chunks = chunker.chunk([Document(text=text, doc_id="doc", extra_info={"source": "fuzz"})])
        _check_chunks(chunks, max_tokens)
        if chunker_class is MarkdownChunker or chunker.chunk_overlap == 0:
            joined = _squash("".join(chunk.text for chunk in chunks))
            assert joined == _squash(text), (text, [chunk.text for chunk in chunks])


def main() -> None:
    """Start the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
