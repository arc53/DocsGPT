"""0030 superseded_messages — distinguish a replaced turn from a lost answer.

``truncate_after`` deletes the tail of a conversation on retry/edit, but a
stream can still own one of those rows: the SSE keepalive pump drains the
generator after a client disconnect, so the old stream runs to completion and
then finalizes into a row that no longer exists. That produced an ERROR-level
``answer_persist_failed`` — indistinguishable from a genuinely orphaned answer,
at the rate users hit retry mid-answer.

The supersede and the late finalize usually happen in DIFFERENT worker
processes, so the signal has to be durable. This table is that signal: one row
per superseded message, written in the same transaction as the delete. There is
deliberately NO foreign key to ``conversation_messages`` — the row it describes
is being deleted microseconds later, and a CASCADE would take the tombstone
with it.

Rows are swept by the existing retention beat; ``superseded_at`` is indexed for
that. Idempotent both ways.

Revision ID: 0030_superseded_messages
Revises: 0029_agent_guardrails
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0030_superseded_messages"
down_revision: Union[str, None] = "0029_agent_guardrails"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS superseded_messages (
            message_id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL,
            superseded_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_superseded_messages_superseded_at
            ON superseded_messages (superseded_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_superseded_messages_superseded_at;")
    op.execute("DROP TABLE IF EXISTS superseded_messages;")
