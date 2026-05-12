"""0007 message_events — durable journal of chat-stream events.

Per-yield journal of every event ``complete_stream`` emits, keyed on the
``conversation_messages.id`` reserved before the LLM call (Tier 1) and a
strictly monotonic ``sequence_no`` allocated by the route handler. The
table is the snapshot half of the Tier 2 snapshot+tail pattern: a client
that drops mid-stream reconnects with the last sequence_no it saw and
the reconnect endpoint replays rows ``WHERE sequence_no > last`` from
this table before tailing the live ``channel:{message_id}`` pub/sub
topic.

The composite PK ``(message_id, sequence_no)`` is the snapshot read
index — for the typical single-message replay shape (one hot
``message_id``, sequential ``sequence_no``) Postgres picks an in-order
index range scan. Highly mixed datasets may surface as a bitmap +
sort plan; the result is the same ascending order either way.

``created_at`` is indexed separately so a future retention janitor can
range-scan ``WHERE created_at < now() - <ttl>`` cheaply — the cost is
one extra btree per insert, which is negligible at v1 emit rates.

``ON DELETE CASCADE`` so deleting a conversation message wipes its
journal in the same transaction.

Revision ID: 0007_message_events
Revises: 0006_idempotency_lease
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0007_message_events"
down_revision: Union[str, None] = "0006_idempotency_lease"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE message_events (
            message_id   UUID NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
            sequence_no  INTEGER NOT NULL,
            event_type   TEXT NOT NULL,
            payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (message_id, sequence_no)
        );
        CREATE INDEX message_events_created_at_idx ON message_events(created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS message_events_created_at_idx;")
    op.execute("DROP TABLE IF EXISTS message_events;")
