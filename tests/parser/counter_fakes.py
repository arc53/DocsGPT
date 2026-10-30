"""Reusable token counters for parser regression tests."""

import pytest

from docsgpt.parser.tokenization import HuggingFaceCounter


class _CollapsingEncoding:
    """WordPiece-like offsets: one token per word, including long unknowns."""

    def __init__(self, text: str) -> None:
        self.ids = []
        self.offsets = []
        cursor = 0
        for word in text.split(" "):
            if word:
                self.ids.append(0)
                self.offsets.append((cursor, cursor + len(word)))
            cursor += len(word) + 1


class _CollapsingTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> _CollapsingEncoding:
        return _CollapsingEncoding(text)


def wordpiece_counter() -> HuggingFaceCounter:
    """Return a counter reproducing WordPiece's collapsed-long-word offsets."""
    return HuggingFaceCounter(_CollapsingTokenizer(), "wordpiece-stub")


class RecordingEncoding:
    """Wraps a tiktoken-like encoding and records the size of each call."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.encode_lengths: list[int] = []
        self.decode_lengths: list[int] = []

    def encode_ordinary(self, text: str):
        self.encode_lengths.append(len(text))
        return self._inner.encode_ordinary(text)

    def decode(self, ids):
        return self._inner.decode(ids)

    def decode_with_offsets(self, ids):
        self.decode_lengths.append(len(ids))
        return self._inner.decode_with_offsets(ids)


class _CharEncoded:
    def __init__(self, offsets) -> None:
        self.offsets = offsets
        self.ids = list(range(len(offsets)))


class CharTokenizer:
    """One token per character; ``skip_whitespace`` gives whitespace no token, as WordPiece does."""

    def __init__(self, skip_whitespace: bool = False) -> None:
        self.skip_whitespace = skip_whitespace
        self.encode_lengths: list[int] = []

    def encode(self, text: str, add_special_tokens: bool = False) -> _CharEncoded:
        self.encode_lengths.append(len(text))
        return _CharEncoded(
            [(i, i + 1) for i, c in enumerate(text) if not (self.skip_whitespace and c.isspace())]
        )


class RecordingTokenizer:
    """Wraps a real HF tokenizer and records the length of every encode."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.encode_lengths: list[int] = []

    def encode(self, text: str, add_special_tokens: bool = False):
        self.encode_lengths.append(len(text))
        return self._inner.encode(text, add_special_tokens=add_special_tokens)


def real_cl100k():
    """Return the real cl100k encoding, skipping the test when it is unavailable."""
    from docsgpt import utils

    try:
        encoding = utils.get_encoding()
        encoding.encode_ordinary("probe")
    except Exception as exc:  # offline CI, same policy as the HF fixture
        pytest.skip(f"cl100k encoding unavailable: {exc}")
    return encoding


def spy_cl100k(monkeypatch, inner=None, window: int | None = None) -> RecordingEncoding:
    """Route every cl100k encode through a recorder, optionally shrinking the tokenizer window.

    Args:
        monkeypatch: The pytest fixture.
        inner: Encoding to wrap; the real cl100k when omitted.
        window: New ``_WINDOW_CHARS``, if given.

    Returns:
        The recorder both ``get_encoding`` seams now return.
    """
    from docsgpt import utils
    from docsgpt.parser import tokenization

    encoding = RecordingEncoding(real_cl100k() if inner is None else inner)
    monkeypatch.setattr(utils, "get_encoding", lambda: encoding)
    monkeypatch.setattr(tokenization, "get_encoding", lambda: encoding)
    if window is not None:
        # raising=False so code without the constant fails on behaviour, not on setup.
        monkeypatch.setattr(tokenization, "_WINDOW_CHARS", window, raising=False)
    return encoding
