"""State builders: the shapes the decision models were trained on, rendered and capped as in training.

A state renders as the release client's ``to_text``: strings as they are, structures as JSON with sorted keys.
The model keeps the first ``max_state_tokens()`` tokens and cuts the rest, so a long field that sorts first
(``passage`` before ``query``, ``source`` after ``claim``) would push the short one out. The builders therefore cap
the long field to the room the short one leaves, by tokens once the tokenizer has loaded and by
``DECISION_MAX_TEXT_CHARS`` characters before that.
"""

from __future__ import annotations

from typing import Any, Callable

from docsgpt.decisions import tokens
from docsgpt.decisions.vendor.arc_decide import to_text

#: Tokens left free for the JSON around the fields.
MARGIN = 64

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
