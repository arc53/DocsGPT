"""Token counts with the decision model's own tokenizer, once it has loaded.

The tokenizer comes up with the model; until then every count is ``None`` and callers fall back to a character
estimate (``DECISION_MAX_TEXT_CHARS``).

The tokenizer refuses a string holding a lone surrogate (``TypeError``), which ``json.loads`` makes of a ``\\ud800``
escape in a tool's output or a request body, so every text is read with each one replaced (``clean``).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from docsgpt.decisions.vendor.arc_decide import to_text

_tokenizer = None
#: A surrogate code point: valid UTF-16 only in a pair, and never valid UTF-8.
_SURROGATE = re.compile("[\ud800-\udfff]")


def use(tokenizer: Any) -> None:
    """Make ``tokenizer`` (``encode``/``decode``, as the release client's) the one counts are taken with."""
    global _tokenizer
    _tokenizer = tokenizer


def reset() -> None:
    """Forget the tokenizer (after a fork, or when the model is released)."""
    use(None)


def clean(text: str) -> str:
    """``text`` with each lone surrogate replaced by U+FFFD, so it encodes as UTF-8 and the tokenizer takes it.

    A pair split into two code points is joined into its character. Text without a surrogate, all text but such
    JSON, is returned as it is (the same object).
    """
    if not _SURROGATE.search(text):
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def encode(text: str) -> Optional[list[int]]:
    """Token ids of ``text`` (read as ``clean`` leaves it), or ``None`` before the tokenizer has loaded."""
    tok = _tokenizer
    return tok.encode(clean(text)) if tok is not None else None


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
