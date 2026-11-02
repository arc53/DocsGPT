"""Fleet-wide snapshot of open SSE connections.

Every SSE stream (``/api/events`` and the message reconnect reader) holds
a lease in its user's sorted set ``user:{user_id}:sse_leases``, scored by
the wall-clock time it last refreshed; a lease older than
``lease_ttl_seconds()`` belongs to a stream that died without cleanup
(see ``docsgpt/streaming/sse_leases.py``). Nothing reads those sets
globally, so this module aggregates them into a point-in-time gauge: how
many users hold at least one live lease and how many live leases exist in
total. The Celery beat task in ``docsgpt/api/user/tasks.py`` logs the
snapshot once a minute as a structured ``sse_gauge`` event.

Leases exist only while the per-user cap is on
(``SSE_MAX_CONCURRENT_PER_USER > 0``); with the cap disabled the gauge
reads zero.
"""

from __future__ import annotations

import time

from docsgpt.events.keys import connection_leases_key
from docsgpt.streaming.sse_leases import lease_ttl_seconds

SSE_LEASES_MATCH = connection_leases_key("*")

# SCAN page size and ZCOUNT pipeline batch size. One pipeline per 500
# keys keeps the sweep at a handful of round-trips even for thousands of
# users.
SCAN_COUNT = 500


def measure_sse_connections(redis_client) -> dict:
    """Count users with open SSE connections and total connections.

    Args:
        redis_client: A connected ``redis.Redis`` instance.

    Returns:
        ``{"connected_users": int, "connections": int}``. Only leases
        refreshed within the lease TTL count, matching the pruning in
        ``acquire_stream_lease``; a key whose leases are all stale, or
        that expires between SCAN and ZCOUNT, contributes nothing.
    """
    # Live means scored strictly after the cutoff: acquire prunes
    # everything at or below it.
    min_score = f"({time.time() - lease_ttl_seconds()}"
    connected_users = 0
    connections = 0

    batch: list = []
    for key in redis_client.scan_iter(match=SSE_LEASES_MATCH, count=SCAN_COUNT):
        batch.append(key)
        if len(batch) >= SCAN_COUNT:
            users, conns = _tally(redis_client, batch, min_score)
            connected_users += users
            connections += conns
            batch = []
    if batch:
        users, conns = _tally(redis_client, batch, min_score)
        connected_users += users
        connections += conns

    return {"connected_users": connected_users, "connections": connections}


def _tally(redis_client, keys: list, min_score: str) -> tuple[int, int]:
    """Return ``(users_with_live_leases, live_lease_total)`` for ``keys``."""
    pipe = redis_client.pipeline(transaction=False)
    for key in keys:
        pipe.zcount(key, min_score, "+inf")
    users = 0
    connections = 0
    for count in pipe.execute():
        if count > 0:
            users += 1
            connections += count
    return users, connections
