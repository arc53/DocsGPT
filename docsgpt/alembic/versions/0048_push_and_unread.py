"""0048 push subscriptions and unread conversations — where a notification goes, and what it leaves behind.

``push_subscriptions`` holds one browser Web Push subscription per row: the
push service endpoint and the two keys the payload is encrypted with. The
endpoint is unique, since one browser profile has one; registering it again
(the same browser after another user signs in) moves it to the new user.
``failure_count`` counts consecutive failed deliveries; a subscription the
push service reports gone (404/410) is deleted.

``conversations.unread_at`` marks a conversation that got a message the user
has not seen (a continuation turn while they were elsewhere). Opening the
conversation clears it. It is a column, not a table: a conversation has one
owner, and the sidebar listing already reads the row.

Idempotent both ways.

Revision ID: 0048_push_and_unread
Revises: 0047_background_jobs
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0048_push_and_unread"
down_revision: Union[str, None] = "0047_background_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            endpoint        TEXT NOT NULL,
            p256dh          TEXT NOT NULL,
            auth            TEXT NOT NULL,
            user_agent      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_success_at TIMESTAMPTZ,
            last_failure_at TIMESTAMPTZ,
            failure_count   INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT push_subscriptions_endpoint_uidx UNIQUE (endpoint)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS push_subscriptions_user_idx ON push_subscriptions (user_id);")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS unread_at TIMESTAMPTZ;")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS unread_at;")
    op.execute("DROP TABLE IF EXISTS push_subscriptions;")
