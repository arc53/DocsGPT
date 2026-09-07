"""0016 conversation visibility — separate "persisted" from "shown in sidebar".

Adds ``conversations.visibility`` (``listed`` | ``hidden``) so a conversation
can be stored without surfacing in the owner's sidebar. Until now display was
inferred from identity columns: ``(api_key IS NULL OR agent_id IS NOT NULL)``.
The backfill reproduces that exact predicate so existing sidebars are
unchanged; new rows set the value explicitly at write time.

Revision ID: 0016_conversation_visibility
Revises: 0015_token_usage_model_id
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0016_conversation_visibility"
down_revision: Union[str, None] = "0015_token_usage_model_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN visibility TEXT NOT NULL DEFAULT 'listed';"
    )
    # NOT VALID first so the ACCESS EXCLUSIVE lock doesn't scan the table;
    # VALIDATE then runs under a weaker lock that allows concurrent reads/writes.
    op.execute(
        "ALTER TABLE conversations "
        "ADD CONSTRAINT conversations_visibility_chk "
        "CHECK (visibility IN ('listed', 'hidden')) NOT VALID;"
    )
    op.execute(
        "ALTER TABLE conversations VALIDATE CONSTRAINT conversations_visibility_chk;"
    )
    # Preserve current sidebars: the old display heuristic showed a
    # conversation when (api_key IS NULL OR agent_id IS NOT NULL); hide the rest.
    op.execute(
        "UPDATE conversations SET visibility = 'hidden' "
        "WHERE NOT (api_key IS NULL OR agent_id IS NOT NULL);"
    )
    # Matches the sidebar query: user_id + visibility, newest first.
    op.execute(
        "CREATE INDEX conversations_user_listed_idx "
        'ON conversations (user_id, date DESC) '
        "WHERE visibility = 'listed';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS conversations_user_listed_idx;")
    op.execute(
        "ALTER TABLE conversations "
        "DROP CONSTRAINT IF EXISTS conversations_visibility_chk;"
    )
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS visibility;")
