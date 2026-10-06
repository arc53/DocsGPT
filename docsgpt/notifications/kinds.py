"""Notification kinds: what happened, and how a notification about it reads.

``notify_user`` takes a ``kind``: a continuation turn passes the source of
the event that woke it (``job``, ``lost``, ``monitor``, ``trigger``,
``approval``, and the monitor notices ``monitor_paused`` and
``monitor_expired``), and a one-time scheduled run that answered in its
conversation passes ``schedule``; another caller may pass its own word. A known kind gets
a fixed heading: the web app shows its translated heading on the toast
(``backgroundJobs.notify.title.<kind>``) and Web Push, which the server words
in English, leads with :data:`KIND_HEADINGS`. An unknown kind reads as the
caller's own title.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

#: The heading a push notification of each known kind leads with.
KIND_HEADINGS: Dict[str, str] = {
    "job": "Background job finished",
    "lost": "Background job interrupted",
    "monitor": "Monitor matched",
    "monitor_paused": "Monitor paused",
    "monitor_expired": "Monitor expired",
    "trigger": "Webhook received",
    "approval": "Approval received",
    "schedule": "Scheduled task finished",
}

#: The push title when there is neither a known kind nor a title.
FALLBACK_TITLE = "DocsGPT"

# The wake title names the job for the model ("run_code finished (job <uuid>)");
# the user needs no id.
_JOB_ID_SUFFIX = re.compile(r"\s*\(job [0-9a-fA-F-]{8,}\)")


# Markdown a notification can't show: removed (code, tables, rules) or reduced to its text.
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_TABLE_ROW = re.compile(r"^[ \t]*\|.*$", re.M)
_RULE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.M)
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.M)
_QUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.M)
_LIST = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", re.M)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_CODE = re.compile(r"`([^`]*)`")

#: Characters of an answer a notification shows.
PREVIEW_CHARS = 280


def plain_preview(text: Optional[str], limit: int = PREVIEW_CHARS) -> str:
    """An answer as a notification shows it: Markdown reduced to plain text, cut at a word boundary.

    Code blocks, table rows and rules are dropped; headings, quotes, list
    markers, emphasis, inline code and links keep only their text.

    Args:
        text: The answer (Markdown).
        limit: The longest string returned, the trailing ellipsis included.

    Returns:
        One line of plain text.
    """
    value = str(text or "")
    for pattern in (_FENCE, _TABLE_ROW, _RULE):
        value = pattern.sub(" ", value)
    for pattern in (_HEADING, _QUOTE, _LIST):
        value = pattern.sub("", value)
    value = _IMAGE.sub(r"\1", value)
    value = _LINK.sub(r"\1", value)
    value = _BOLD.sub(r"\2", value)
    value = _ITALIC.sub(r"\1", value)
    value = _CODE.sub(r"\1", value)
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    cut = value[: max(limit - 1, 0)]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def heading(kind: Optional[str]) -> Optional[str]:
    """The heading for a known kind, or None."""
    return KIND_HEADINGS.get(kind or "")


def user_title(title: Optional[str]) -> str:
    """A wake title as the user reads it: without the job id meant for the model.

    Args:
        title: The event's title.

    Returns:
        The title, trimmed, with any ``(job <id>)`` removed.
    """
    return " ".join(_JOB_ID_SUFFIX.sub("", str(title or "")).split())


def push_text(kind: Optional[str], title: str, body: str) -> Tuple[str, str]:
    """The title and body a Web Push notification shows.

    A known kind leads with its heading and moves the caller's title into the
    body ("Monitor matched" / "BTC below $50k: It is $49,800."); an unknown
    kind keeps the caller's title.

    Args:
        kind: The notification kind.
        title: The caller's one-line title.
        body: The caller's preview.

    Returns:
        ``(title, body)``, unbounded (the payload builder clips them).
    """
    title = user_title(title)
    body = (body or "").strip()
    known = heading(kind)
    if known is None:
        return title or FALLBACK_TITLE, body
    if title and body:
        return known, f"{title}: {body}"
    return known, title or body
