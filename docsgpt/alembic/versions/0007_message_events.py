"""0007 message_events — durable journal of chat-stream events.

Snapshot half of the chat-stream snapshot+tail pattern. Composite PK
``(message_id, sequence_no)``, ``created_at`` indexed for retention
sweeps, ``ON DELETE CASCADE`` from ``conversation_messages``.

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
