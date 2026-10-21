"""0058 conversation label sources — what a label row was built from, for its freshness.

* ``conversation_labels.source_updated_at``: the ``updated_at`` of the
  message the row's state was built from as the sweep read it (for a
  conversation-level row, the latest over the conversation's messages).
* ``conversation_labels.source_hash``: a hash of what the states read of
  that message (prompt, response, sources, status, timestamp; for a
  conversation, of its messages' hashes in order), computed in SQL by
  ``_message_hash`` in ``repositories/conversation_labels.py``.

A label is current while its message is unchanged since ``source_updated_at``
or, past it, hashes the same: feedback or a finished background job touch
``updated_at`` without changing what was labelled, and an edit while the
sweep ran leaves the row stale. Rows from before this migration have both
NULL and keep the old test (``created_at`` at or after the message's
``updated_at``), so nothing is asked again on deploy. Both columns are
nullable without a default, so adding them rewrites nothing.

Idempotent both ways. Downgrade drops the two columns.

Revision ID: 0058_conversation_label_sources
Revises: 0057_conversation_labels
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0058_conversation_label_sources"
down_revision: Union[str, None] = "0057_conversation_labels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_labels "
        "ADD COLUMN IF NOT EXISTS source_updated_at timestamptz, "
        "ADD COLUMN IF NOT EXISTS source_hash text;"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE conversation_labels "
        "DROP COLUMN IF EXISTS source_updated_at, "
        "DROP COLUMN IF EXISTS source_hash;"
    )
