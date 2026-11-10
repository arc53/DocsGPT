"""The marker a scheduled run without tool calling opens its answer with when it can't do its task.

A model that can call tools reports it with ``report_cannot_complete`` instead.
"""

from __future__ import annotations

import re
from typing import Optional

CANNOT_COMPLETE_MARKER = "CANNOT_COMPLETE:"

# The marker at the start of the text, after whatever a model puts in front of
# it (markdown, a list bullet, an emoji), with an ASCII or full-width colon.
_OPENING_MARKER = re.compile(
    r"\A(?:[^\w\n]|_)*cannot(?:[ -]|\\?_)complete[*_` \t]*[:：](?P<rest>[^\n]*)",
    re.IGNORECASE,
)
_REASON_CAP = 500
_NO_REASON = "the agent reported that it cannot complete the task"


def _clean(line: str) -> str:
    """A line without surrounding whitespace and markdown emphasis."""
    return line.strip().strip("*_`").strip()


def cannot_complete_reason(text: Optional[str]) -> Optional[str]:
    """The reason line of text that opens with the marker, else None.

    Only the very start of the text counts: a marker further down, or the
    word "cannot" anywhere, leaves it an ordinary answer.
    """
    stripped = (text or "").lstrip()
    match = _OPENING_MARKER.match(stripped)
    if match is None:
        return None
    reason = _clean(match.group("rest"))
    if not reason:
        # The model put the reason on the line after the marker.
        following = (_clean(line) for line in stripped[match.end():].splitlines())
        reason = next((line for line in following if line), "")
    return (reason or _NO_REASON)[:_REASON_CAP]


def drop_cannot_complete_marker(text: str) -> str:
    """The text with its opening marker line reduced to its reason; later lines are left alone."""
    stripped = text.lstrip()
    match = _OPENING_MARKER.match(stripped)
    if match is None:
        return text
    rest = _clean(match.group("rest"))
    remainder = stripped[match.end():]
    return f"{rest}{remainder}".strip() if rest else remainder.strip()
