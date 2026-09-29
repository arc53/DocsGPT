"""0038 resource access settings — per-asset sharing switches and tool chat prefs.

``resource_share_settings`` holds the owner's per-asset switches that adjust
what the fixed roles may do on one shared resource ("Editors can share",
"Viewers can see logs", ...). One row per ``(resource_type, resource_id)``;
a missing row means every switch is at its default. The table is polymorphic
like ``team_resource_grants``, so it has no FK and the switch keys are
validated in code (``docsgpt/api/user/resource_access.py``), which keeps new
switches migration-free.

``user_tool_preferences`` is the personal "In my chats" switch for a tool
shared with the caller. A grantee can't write the owner's ``user_tools.status``
(that is the owner's own chat setting), so each grantee gets a row here.
A missing row means off: sharing a tool never adds it to anyone's chats.

Idempotent both ways.

Revision ID: 0038_resource_access_settings
Revises: 0037_request_traces
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0038_resource_access_settings"
down_revision: Union[str, None] = "0037_request_traces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_share_settings (
            resource_type TEXT NOT NULL
                CONSTRAINT resource_share_settings_type_check
                CHECK (resource_type IN ('agent', 'source', 'prompt', 'tool')),
            resource_id   UUID NOT NULL,
            settings      JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_by    TEXT,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (resource_type, resource_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_tool_preferences (
            user_id    TEXT NOT NULL,
            tool_id    UUID NOT NULL REFERENCES user_tools(id) ON DELETE CASCADE,
            in_chat    BOOLEAN NOT NULL DEFAULT false,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, tool_id)
        );
        CREATE INDEX IF NOT EXISTS user_tool_preferences_tool_idx
            ON user_tool_preferences (tool_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_tool_preferences;")
    op.execute("DROP TABLE IF EXISTS resource_share_settings;")
