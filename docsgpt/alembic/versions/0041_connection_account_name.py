"""0041 connection account name — what the user calls an account.

``account_label`` identifies an account: the email an OAuth sign-in returns,
or a hint of a pasted key. Signing in again finds the connection by it, so it
cannot be renamed. ``account_name`` is the name the user gives the account
("Alerts bot", "Work"), shown instead of the label and used to tell two
accounts of one service apart, for people and for the model. NULL means the
user never named it.

Idempotent both ways.

Revision ID: 0041_connection_account_name
Revises: 0040_connections
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0041_connection_account_name"
down_revision: Union[str, None] = "0040_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE connector_sessions ADD COLUMN IF NOT EXISTS account_name TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE connector_sessions DROP COLUMN IF EXISTS account_name;")
