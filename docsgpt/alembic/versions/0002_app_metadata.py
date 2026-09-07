"""0002 app_metadata — singleton key/value table for instance-wide state.

Used by the startup version-check client to persist the anonymous
instance UUID and a one-shot "notice shown" flag. Both values are tiny
plain-text strings; this is a deliberate generic-config table rather
than dedicated columns so future one-off settings (telemetry opt-in
timestamps, feature-flag overrides, etc.) don't each need their own
migration.

Revision ID: 0002_app_metadata
Revises: 0001_initial
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0002_app_metadata"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app_metadata (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_metadata;")
