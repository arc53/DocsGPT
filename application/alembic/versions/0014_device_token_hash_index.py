"""0014 device token_hash index — index the per-request token lookup.

``find_by_token_hash`` runs on every CLI request but ``token_hash`` was
unindexed. Token uniqueness is guaranteed at generation, so a UNIQUE
index is safe (and doubles as a guard against accidental collisions).

Revision ID: 0014_device_token_hash_index
Revises: 0013_devices_approval_modes
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0014_device_token_hash_index"
down_revision: Union[str, None] = "0013_devices_approval_modes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX devices_token_hash_uidx ON devices(token_hash);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS devices_token_hash_uidx;")
