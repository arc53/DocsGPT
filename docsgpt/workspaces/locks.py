"""The lock that keeps a move and outside access on the same owner's items one after the other."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text


def lock_owner_items(conn: Connection, *owners: Optional[str]) -> None:
    """Hold these owners' items for this transaction against a move, or a move against this transaction.

    A move checks once that no agent with a key, public link or webhook would
    use what it moves; turning one on, or saving refs on an agent that has
    one, checks once that the agent uses no one else's item. Each check sees
    the other's writes only after they commit, so both take this lock before
    checking and run one after the other. Take it before locking any row a
    move updates, or the two can deadlock.

    Args:
        conn: Open connection inside a transaction; the lock lasts until it ends.
        owners: The items' owners (a person, or a team's principal); empty ones are skipped.
    """
    # Sorted, so two callers holding several never wait on each other in a cycle.
    for owner in sorted({o for o in owners if o}):
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('owner-items:' || :owner, 0))"), {"owner": owner}
        )
