"""Stream/topic key derivations shared by publisher and SSE consumer.

Single source of truth for the per-user Redis Streams key and pub/sub
topic name. Both must agree exactly — a typo here splits the
publisher's writes from the consumer's reads.
"""

from __future__ import annotations


def stream_key(user_id: str) -> str:
    """Redis Streams key holding the durable backlog for ``user_id``."""
    return f"user:{user_id}:stream"


def topic_name(user_id: str) -> str:
    """Redis pub/sub channel used for live fan-out to ``user_id``."""
    return f"user:{user_id}"


def connection_counter_key(user_id: str) -> str:
    """Redis counter tracking active SSE connections for ``user_id``."""
    return f"user:{user_id}:sse_count"


def replay_budget_key(user_id: str) -> str:
    """Redis counter tracking snapshot replays for ``user_id`` in the
    rolling rate-limit window."""
    return f"user:{user_id}:replay_count"


def stream_id_compare(a: str, b: str) -> int:
    """Compare two Redis Streams ids. Returns -1, 0, 1 like ``cmp``.

    Stream ids are ``ms-seq`` strings; comparing as strings would be wrong
    once ``ms`` straddles digit-count boundaries. We parse and compare
    as ``(int, int)`` tuples.

    Raises ``ValueError`` on malformed input. Callers must pre-validate
    against ``_STREAM_ID_RE`` (or equivalent) — a lex fallback here let
    a malformed id compare lex-greater than a real one and silently pin
    dedup forever.
    """
    a_ms, _, a_seq = a.partition("-")
    b_ms, _, b_seq = b.partition("-")
    a_tuple = (int(a_ms), int(a_seq) if a_seq else 0)
    b_tuple = (int(b_ms), int(b_seq) if b_seq else 0)
    if a_tuple < b_tuple:
        return -1
    if a_tuple > b_tuple:
        return 1
    return 0
