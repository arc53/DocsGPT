"""Presence: which conversation each of a user's tabs shows, and whether anyone is looking.

Each tab reports ``{tab_id, conversation_id, visible}`` when its visibility or
route changes and every ~20 s while visible (``POST /api/presence``). The
reports live in one Redis hash per user, ``presence:{user_id}``, one field per
tab, stamped with the report time. An entry older than
:data:`PRESENCE_TTL_SECONDS` no longer counts, and the hash expires that long
after the last report, so a tab that stopped reporting drops out on its own;
a tab that closes says so (``closing``) and is removed at once.

Two questions are asked of it before notifying:

* :func:`is_watching`: some tab is visible with that conversation open. Only
  a visible tab counts, and only while it keeps reporting.
* :func:`has_open_tab`: a tab could show a toast. That is a live event-stream
  connection (its lease in ``user:{id}:sse_leases``), which a hidden tab
  keeps open, or a visible tab's report. A hidden tab's report alone does not
  count: a tab that closed without saying so reports "hidden" last. When the
  connection cap is off (no leases), a fresh report of either kind counts.

Both answer ``False`` when Redis is unavailable or failing, so a notification
still goes out (as push, or at least the unread mark).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from docsgpt.cache import get_redis_instance
from docsgpt.core.settings import settings
from docsgpt.events.keys import connection_leases_key

logger = logging.getLogger(__name__)

#: Seconds a tab's report counts; clients re-report every ~20 s while visible.
PRESENCE_TTL_SECONDS = 45

#: Tabs one user's presence keeps; past it the stalest reports are dropped.
MAX_TABS = 32


def presence_key(user_id: str) -> str:
    """The Redis hash holding a user's tab reports."""
    return f"presence:{user_id}"


def report(
    user_id: str,
    tab_id: str,
    conversation_id: Optional[str],
    visible: bool,
    *,
    closing: bool = False,
    now: Optional[float] = None,
) -> bool:
    """Record what one tab shows; ``closing`` forgets the tab.

    Args:
        user_id: The signed-in user.
        tab_id: The tab's own random id.
        conversation_id: The conversation it shows, or None.
        visible: Whether the tab is visible.
        closing: The tab is going away.
        now: The report time (tests).

    Returns:
        False when Redis is unavailable or the write failed.
    """
    redis = get_redis_instance()
    if redis is None:
        return False
    key = presence_key(user_id)
    try:
        if closing:
            redis.hdel(key, tab_id)
            return True
        entry = {
            "conversation_id": str(conversation_id).lower() if conversation_id else None,
            "visible": bool(visible),
            "at": float(now if now is not None else time.time()),
        }
        pipe = redis.pipeline()
        pipe.hset(key, tab_id, json.dumps(entry))
        pipe.expire(key, PRESENCE_TTL_SECONDS)
        pipe.hlen(key)
        results = pipe.execute()
        if int(results[-1] or 0) > MAX_TABS:
            _prune(redis, key, now)
        return True
    except Exception:
        logger.debug("presence report failed for user %s", user_id, exc_info=True)
        return False


def _prune(redis: Any, key: str, now: Optional[float]) -> None:
    """Drop stale reports, then the oldest ones past :data:`MAX_TABS`."""
    entries = _decode_all(redis.hgetall(key))
    cutoff = (now if now is not None else time.time()) - PRESENCE_TTL_SECONDS
    stale = [tab for tab, entry in entries.items() if entry["at"] < cutoff]
    fresh = sorted(
        ((tab, entry) for tab, entry in entries.items() if entry["at"] >= cutoff),
        key=lambda item: item[1]["at"],
        reverse=True,
    )
    stale += [tab for tab, _ in fresh[MAX_TABS:]]
    if stale:
        redis.hdel(key, *stale)


def _decode_all(raw: Optional[Dict[Any, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for tab, value in (raw or {}).items():
        tab_id = tab.decode() if isinstance(tab, (bytes, bytearray)) else str(tab)
        try:
            entry = json.loads(value)
            out[tab_id] = {
                "conversation_id": entry.get("conversation_id"),
                "visible": bool(entry.get("visible")),
                "at": float(entry.get("at") or 0),
            }
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def tabs(user_id: str, *, now: Optional[float] = None) -> Optional[List[Dict[str, Any]]]:
    """The user's tabs that reported within the TTL.

    Returns:
        ``[{tab_id, conversation_id, visible, at}]``, or None when Redis is
        unavailable or failing.
    """
    redis = get_redis_instance()
    if redis is None:
        return None
    try:
        entries = _decode_all(redis.hgetall(presence_key(user_id)))
    except Exception:
        logger.debug("presence read failed for user %s", user_id, exc_info=True)
        return None
    cutoff = (now if now is not None else time.time()) - PRESENCE_TTL_SECONDS
    return [{"tab_id": tab, **entry} for tab, entry in entries.items() if entry["at"] >= cutoff]


def is_watching(user_id: str, conversation_id: Optional[str], *, now: Optional[float] = None) -> bool:
    """Whether a visible tab of the user shows ``conversation_id``; False when unknown."""
    if not user_id or not conversation_id:
        return False
    wanted = str(conversation_id).lower()
    return any(t["visible"] and t["conversation_id"] == wanted for t in tabs(user_id, now=now) or [])


def _live_stream_count(user_id: str, now: float) -> Optional[int]:
    """Event-stream connections of the user with a live lease; None when leases are off or unreadable."""
    if int(settings.SSE_MAX_CONCURRENT_PER_USER) <= 0:
        return None
    redis = get_redis_instance()
    if redis is None:
        return None
    from docsgpt.streaming.sse_leases import lease_ttl_seconds

    try:
        return int(redis.zcount(connection_leases_key(user_id), now - lease_ttl_seconds(), "+inf") or 0)
    except Exception:
        logger.debug("SSE lease count failed for user %s", user_id, exc_info=True)
        return None


def has_open_tab(user_id: str, *, now: Optional[float] = None) -> bool:
    """Whether a tab of the user could show a toast now; False when unknown.

    A live event-stream connection or a visible tab's report counts. Without
    connection leases to ask, any fresh report counts.
    """
    if not user_id:
        return False
    moment = now if now is not None else time.time()
    reports = tabs(user_id, now=moment)
    if reports is None:
        return False
    if any(t["visible"] for t in reports):
        return True
    streams = _live_stream_count(user_id, moment)
    if streams is None:
        return bool(reports) and int(settings.SSE_MAX_CONCURRENT_PER_USER) <= 0
    return streams > 0
