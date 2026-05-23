"""0009 default chat tools — users.tool_preferences + memories.tool_id.

Adds ``users.tool_preferences`` JSONB and drops the
``memories.tool_id`` FK to ``user_tools`` (synthetic default-tool ids
have no ``user_tools`` row). Delete-cascade for real tools is kept via
an AFTER DELETE trigger on ``user_tools``. Idempotent both ways.

Revision ID: 0009_tool_preferences
Revises: 0008_ingest_progress_status
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0009_tool_preferences"
down_revision: Union[str, None] = "0008_ingest_progress_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS tool_preferences JSONB
            NOT NULL DEFAULT '{}'::jsonb;
        """
    )

    op.execute(
        "ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_tool_id_fkey;"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION cleanup_tool_memories() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM memories WHERE tool_id = OLD.id;
            RETURN OLD;
        END;
        $$;
        """
    )
    # DROP-then-CREATE — no CREATE OR REPLACE TRIGGER for this signature.
    op.execute(
        "DROP TRIGGER IF EXISTS user_tools_cleanup_memories ON user_tools;"
    )
    op.execute(
        "CREATE TRIGGER user_tools_cleanup_memories "
        "AFTER DELETE ON user_tools "
        "FOR EACH ROW EXECUTE FUNCTION cleanup_tool_memories();"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS user_tools_cleanup_memories ON user_tools;"
    )
    op.execute("DROP FUNCTION IF EXISTS cleanup_tool_memories();")
    # DESTRUCTIVE: restoring the FK requires every memories.tool_id to
    # reference a real user_tools row. Any memory written by a built-in
    # default tool (synthetic uuid5 id, no user_tools row) is permanently
    # DELETED here so the constraint can be re-created. Downgrading 0009
    # therefore loses all built-in-memory-tool data — by necessity, since
    # the restored schema cannot represent it.
    op.execute(
        """
        DELETE FROM memories
        WHERE tool_id IS NOT NULL
          AND tool_id NOT IN (SELECT id FROM user_tools);
        """
    )
    op.execute(
        """
        ALTER TABLE memories
            ADD CONSTRAINT memories_tool_id_fkey
            FOREIGN KEY (tool_id) REFERENCES user_tools(id) ON DELETE CASCADE;
        """
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS tool_preferences;")
