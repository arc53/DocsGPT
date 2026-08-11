"""0013 devices approval modes — collapse to ask/full.

Drops the ``writes-only`` mode and renames ``never`` to ``full``. Existing
rows are converted (``writes-only`` -> ``ask``, ``never`` -> ``full``) and
the CHECK constraint is rewritten to allow only ``ask`` / ``full``.

Revision ID: 0013_devices_approval_modes
Revises: 0012_remote_devices
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0013_devices_approval_modes"
down_revision: Union[str, None] = "0012_remote_devices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old constraint before rewriting values so the conversion
    # never trips the stale CHECK.
    op.execute(
        "ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_approval_mode_chk;"
    )
    op.execute(
        "UPDATE devices SET approval_mode = 'ask' WHERE approval_mode = 'writes-only';"
    )
    op.execute(
        "UPDATE devices SET approval_mode = 'full' WHERE approval_mode = 'never';"
    )
    op.execute(
        "ALTER TABLE devices ADD CONSTRAINT devices_approval_mode_chk "
        "CHECK (approval_mode IN ('ask', 'full'));"
    )


def downgrade() -> None:
    # ``never`` is restored from ``full``. ``writes-only`` is gone — rows
    # that were converted to ``ask`` stay ``ask`` (no reverse mapping).
    op.execute(
        "ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_approval_mode_chk;"
    )
    op.execute(
        "UPDATE devices SET approval_mode = 'never' WHERE approval_mode = 'full';"
    )
    op.execute(
        "ALTER TABLE devices ADD CONSTRAINT devices_approval_mode_chk "
        "CHECK (approval_mode IN ('ask', 'writes-only', 'never'));"
    )
