"""Token counts with the decision model's own tokenizer, once it has loaded.

The tokenizer comes up with the model; until then every count is ``None`` and callers fall back to a character
estimate (``DECISION_MAX_TEXT_CHARS``).
"""

from __future__ import annotations

from typing import Any, Optional

from docsgpt.decisions.vendor.arc_decide import to_text

_tokenizer = None


def use(tokenizer: Any) -> None:
    """Make ``tokenizer`` (``encode``/``decode``, as the release client's) the one counts are taken with."""
    global _tokenizer
    _tokenizer = tokenizer


def reset() -> None:
    """Forget the tokenizer (after a fork, or when the model is released)."""
    use(None)


def encode(text: str) -> Optional[list[int]]:
    """Token ids of ``text``, or ``None`` before the tokenizer has loaded."""
    tok = _tokenizer
    return tok.encode(text) if tok is not None else None


def decode(ids: list[int]) -> str:
    """Text of ``ids``; only valid once ``encode`` has returned ids."""
    return _tokenizer.decode(ids)


def count_tokens(text: str) -> Optional[int]:
    """Tokens in ``text``, or ``None`` before the tokenizer has loaded."""
    ids = encode(text)
    return None if ids is None else len(ids)


def state_tokens(state: Any) -> Optional[int]:
    """Tokens in a rendered state, before any truncation."""
    return count_tokens(to_text(state))
