"""Notification kinds: what happened, and how a notification about it reads.

``notify_user`` takes a ``kind``: a continuation turn passes the source of
the event that woke it (``job``, ``lost``, ``monitor``, ``trigger``,
``approval``), and a feature that notifies on its own passes its own word
(``monitor_paused``). A known kind gets a fixed heading: the web app shows
its translated heading on the toast (``backgroundJobs.notify.title.<kind>``)
and Web Push, which the server words in English, leads with
:data:`KIND_HEADINGS`. An unknown kind reads as the caller's own title.
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
    "trigger": "Webhook received",
    "approval": "Approval received",
}

#: The push title when there is neither a known kind nor a title.
FALLBACK_TITLE = "DocsGPT"

# The wake title names the job for the model ("run_code finished (job <uuid>)");
# the user needs no id.
_JOB_ID_SUFFIX = re.compile(r"\s*\(job [0-9a-fA-F-]{8,}\)")


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
