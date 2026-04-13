"""0002 add unique constraints for notes and connector_sessions.

The memories table already has ``memories_user_tool_path_uidx`` from the
0001 baseline. Notes and connector_sessions were missing unique constraints
that their repository upsert logic depends on.

Before creating the indexes, duplicate rows are cleaned up — keeping only
the row with the latest ``id`` (UUID, lexicographic max) per group.

Revision ID: 0002_add_unique_constraints
Revises: 0001_initial
Create Date: 2026-04-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002_add_unique_constraints"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate notes: keep one row per (user_id, tool_id)
    op.execute("""
        DELETE FROM notes
        WHERE id NOT IN (
            SELECT DISTINCT ON (user_id, tool_id) id
            FROM notes
            ORDER BY user_id, tool_id, created_at DESC
        );
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS notes_user_tool_uidx "
        "ON notes (user_id, tool_id);"
    )

    # Deduplicate connector_sessions: keep one row per (user_id, provider)
    op.execute("""
        DELETE FROM connector_sessions
        WHERE id NOT IN (
            SELECT DISTINCT ON (user_id, provider) id
            FROM connector_sessions
            ORDER BY user_id, provider, created_at DESC
        );
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS connector_sessions_user_provider_uidx "
        "ON connector_sessions (user_id, provider);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS connector_sessions_user_provider_uidx;")
    op.execute("DROP INDEX IF EXISTS notes_user_tool_uidx;")
