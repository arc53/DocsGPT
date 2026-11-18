"""0056 conversation passthrough — the request values a conversation was asked with.

* ``conversations.passthrough``: the scalar ``passthrough`` values of the
  conversation's latest turn (bounded, see
  ``docsgpt/api/answer/services/passthrough.py``), so an owner can tell which
  end user an API or widget conversation came from. Each turn's Logs row keeps
  its own copy in ``user_logs.data``.

Idempotent both ways. Downgrade drops the column.

Revision ID: 0056_conversation_passthrough
Revises: 0055_content_scores
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0056_conversation_passthrough"
down_revision: Union[str, None] = "0055_content_scores"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS passthrough JSONB;")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS passthrough;")
