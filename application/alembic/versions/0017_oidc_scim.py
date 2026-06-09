"""0017 oidc scim — users.active flag + auth_events audit table.

``users.active`` backs SCIM deprovisioning: deactivated users are refused new
OIDC sessions and their live sessions are denylisted until they expire.
``auth_events`` is an append-only audit trail of login / logout / provisioning
events keyed by ``user_id``.

Revision ID: 0017_oidc_scim
Revises: 0016_conversation_visibility
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0017_oidc_scim"
down_revision: Union[str, None] = "0016_conversation_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE;")
    op.execute(
        """
        CREATE TABLE auth_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            event TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX auth_events_user_idx ON auth_events (user_id, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_events;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS active;")
