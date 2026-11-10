"""The marker a scheduled run's answer opens with when the agent cannot do its task."""

from __future__ import annotations

import re
from typing import Optional

CANNOT_COMPLETE_MARKER = "CANNOT_COMPLETE:"

# A line that opens with the marker, allowing the markdown a model wraps it in
# (``**CANNOT_COMPLETE:**``, ``## Cannot complete:``, ``CANNOT\_COMPLETE:``).
_MARKER_LINE = re.compile(
    r"^[ \t>#*_`]*cannot(?:[ -]|\\?_)complete[*_` \t]*:(?P<rest>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)
_REASON_CAP = 500
_NO_REASON = "the agent reported that it cannot complete the task"


def _clean(line: str) -> str:
    return line.strip().strip("*_`").strip()


def cannot_complete_reason(answer: Optional[str]) -> Optional[str]:
    """The reason line of an answer that opens with the marker, else None.

    Only the very start of the answer counts: a marker further down, or the
    word "cannot" anywhere, leaves the answer an ordinary one.
    """
    text = (answer or "").lstrip()
    match = _MARKER_LINE.match(text)
    if match is None:
        return None
    reason = _clean(match.group("rest"))
    if not reason:
        # The model put the reason on the line after the marker.
        following = (_clean(line) for line in text[match.end():].splitlines())
        reason = next((line for line in following if line), "")
    return (reason or _NO_REASON)[:_REASON_CAP]


def drop_cannot_complete_marker(answer: str) -> str:
    """The answer with each marker line reduced to its reason, for display."""
    return _MARKER_LINE.sub(lambda m: _clean(m.group("rest")), answer).strip()
