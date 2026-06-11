"""0018 tool_call_attempts attribution — record user/agent on the journal.

Adds ``tool_call_attempts.user_id`` / ``agent_id`` so tool analytics can
attribute attempts that never get a ``message_id`` — headless runs
(scheduled / webhook) execute tools before any conversation message
exists, and parse-failure rows never reach one at all. Existing rows are
backfilled through their parent message where one exists.

Revision ID: 0018_tool_attempts_attribution
Revises: 0017_oidc_scim
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0018_tool_attempts_attribution"
down_revision: Union[str, None] = "0017_oidc_scim"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tool_call_attempts ADD COLUMN user_id TEXT;")
    op.execute("ALTER TABLE tool_call_attempts ADD COLUMN agent_id UUID;")
    op.execute(
        """
        UPDATE tool_call_attempts t
           SET user_id = m.user_id,
               agent_id = c.agent_id
          FROM conversation_messages m
          LEFT JOIN conversations c ON c.id = m.conversation_id
         WHERE t.message_id = m.id
           AND t.user_id IS NULL;
        """
    )
    op.execute(
        "CREATE INDEX tool_call_attempts_user_ts_idx "
        "ON tool_call_attempts (user_id, attempted_at DESC) "
        "WHERE user_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tool_call_attempts_user_ts_idx;")
    op.execute("ALTER TABLE tool_call_attempts DROP COLUMN IF EXISTS agent_id;")
    op.execute("ALTER TABLE tool_call_attempts DROP COLUMN IF EXISTS user_id;")
