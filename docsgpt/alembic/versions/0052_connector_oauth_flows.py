"""0052 connector OAuth flows — a connector sign-in is finished by the user who started it.

* ``connector_oauth_flows``: one row per OAuth sign-in, bound to the user who
  started it. The provider echoes a random ``state`` whose hash is stored
  here, with the app origin the sign-in started from. The app's callback
  page posts the code and state with its own login; the row is used up and
  the sign-in finished only when that login is the user who started it. A
  victim who completes a sign-in someone else started cannot hand that
  person the account. No credentials are stored here.

Idempotent both ways. Downgrade drops sign-ins in progress.

Revision ID: 0052_connector_oauth_flows
Revises: 0051_device_jobs_links
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0052_connector_oauth_flows"
down_revision: Union[str, None] = "0051_device_jobs_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_oauth_flows (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       TEXT NOT NULL,
            provider      TEXT NOT NULL,
            connection_id UUID NOT NULL REFERENCES connector_sessions(id) ON DELETE CASCADE,
            state_hash    TEXT NOT NULL CONSTRAINT connector_oauth_flows_state_hash_key UNIQUE,
            return_origin TEXT NOT NULL,
            expires_at    TIMESTAMPTZ NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS connector_oauth_flows_expires_idx ON connector_oauth_flows (expires_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS connector_oauth_flows;")
