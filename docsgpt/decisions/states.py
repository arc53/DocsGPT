"""State builders: the shapes the decision models were trained on, rendered and capped as in training.

A state renders as the release client's ``to_text``: strings as they are, structures as JSON with sorted keys.
The model keeps the first ``max_state_tokens()`` tokens and cuts the rest, so a long field that sorts first
(``passage`` before ``query``, ``source`` after ``claim``) would push the short one out. The builders therefore cap
the long field to the room the short one leaves, by tokens once the tokenizer has loaded and by
``DECISION_MAX_TEXT_CHARS`` characters before that.

On a CPU a whole chunk is too slow to score on the answer path, so relevance there reads a passage cut to a few
hundred tokens by ``best_window``: arc-decide's measured selection (its ``cap_passage`` with ``select="best"``),
which keeps the chunk's head and the window that shares the most words with the query.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from docsgpt.decisions import tokens
from docsgpt.decisions.vendor.arc_decide import to_text

#: Tokens left free for the JSON around the fields.
MARGIN = 64
#: Tokens of a chunk's start (its title and headings) that ``best_window`` always keeps.
HEAD_TOKENS = 64

_WORD = re.compile(r"\w+")

render: Callable[[Any], str] = to_text


def max_state_tokens() -> int:
    """Tokens of state the selected model reads (2,048 for both published models)."""
    from docsgpt.decisions.models import V02, select

    return (select() or V02).max_state_tokens


def _capped(build: Callable[[str], dict], long_text: str) -> dict:
    """``build(long_text)``, with ``long_text`` cut so the whole rendered state fits the model's token limit."""
    from docsgpt.core.settings import settings

    ids = tokens.encode(long_text)
    if ids is None:
        return build(long_text[: settings.DECISION_MAX_TEXT_CHARS])
    budget = max_state_tokens() - MARGIN
    state = build(long_text)
    if tokens.state_tokens(state) <= budget:
        return state
    keep = budget - tokens.state_tokens(build(""))
    # JSON escapes add tokens the raw text does not have: cut, measure the rendered state, cut the excess
    while True:
        state = build(tokens.decode(ids[: max(keep, 0)]))
        over = tokens.state_tokens(state) - budget
        if over <= 0 or keep <= 0:
            return state
        keep -= over


def relevance(query: str, passage: str) -> dict:
    """``{"query", "passage"}``: does the passage help answer the query (questions ``relevant``, ``grade``)."""
    return _capped(lambda p: {"query": query, "passage": p}, passage)


def grounding(source: str, claim: str) -> dict:
    """``{"source", "claim"}``: is one claim supported by the source (question ``supported``)."""
    return _capped(lambda s: {"source": s, "claim": claim}, source)


def text(t: str) -> dict:
    """``{"text"}``: a user message, a retrieved chunk or a tool output (questions ``injection``, ``severity``)."""
    return {"text": t}


def plain(t: str) -> str:
    """A bare string, for open yes/no and policy questions."""
    return t


def cpu_runtime(runtime: Optional[str]) -> bool:
    """Whether a ``ModelInfo.runtime`` is a CPU one: ONNX here or on a decide server, or the API process's model
    (``api-process``, which runs ONNX) seen from a worker. vLLM, torch and servers that report no runtime are not."""
    if not runtime:
        return False
    base = runtime.split(":", 1)[1] if runtime.startswith("api-process:") else runtime
    return base == "api-process" or base.startswith("onnx")


def _terms(text: str) -> set[str]:
    """Query words worth matching: words of 3+ characters, and single CJK characters (CJK has no spaces)."""
    words = {w for w in _WORD.findall(text.lower()) if len(w) >= 3}
    return words | {c for c in text if "\u3040" <= c <= "\u9fff"}


def _best_window(ids: list[int], query: str, max_tokens: int) -> str:
    """The first ``HEAD_TOKENS`` tokens plus the later window that contains the most query words."""
    head, size = ids[:HEAD_TOKENS], max_tokens - HEAD_TOKENS
    rest, terms = ids[HEAD_TOKENS:], _terms(query)
    starts = range(0, max(1, len(rest) - size + 1), max(1, size // 2))

    def score(i: int) -> int:
        window = tokens.decode(rest[i:i + size]).lower()
        return sum(t in window for t in terms)

    best = max(starts, key=lambda i: (score(i), -i))
    gap = " ...\n" if best else ""
    return tokens.decode(head) + gap + tokens.decode(rest[best:best + size])


def best_window(passage: str, query: str, max_tokens: int) -> Optional[str]:
    """``passage`` cut to ``max_tokens`` tokens: its head plus the window that best matches ``query``.

    A passage that fits is returned as it is; without a query (or with no room past the head) the first
    ``max_tokens`` tokens are kept.

    Returns:
        The passage to score, or ``None`` before the tokenizer has loaded.
    """
    ids = tokens.encode(passage)
    if ids is None:
        return None
    if len(ids) <= max_tokens:
        return passage
    if query and max_tokens > HEAD_TOKENS:
        return _best_window(ids, query, max_tokens)
    return tokens.decode(ids[:max_tokens])
