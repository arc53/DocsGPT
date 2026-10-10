"""Reusable token counters for parser regression tests."""

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
