"""Per-chat-message stream key derivations.

Single source of truth for the Redis pub/sub topic name and any
auxiliary keys that the chat-stream snapshot+tail reconnect path
shares between the writer (``complete_stream`` + journal) and the
reader (``/api/messages/<id>/events`` reconnect endpoint).
"""

from __future__ import annotations


def message_topic_name(message_id: str) -> str:
    """Redis pub/sub channel for live fan-out of one chat message.

    Subscribers tail this topic for every event that ``complete_stream``
    yielded after the SUBSCRIBE-ack arrived; older events are recovered
    from the ``message_events`` snapshot half of the pattern.
    """
    return f"channel:{message_id}"
