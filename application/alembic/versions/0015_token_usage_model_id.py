"""0015 token_usage model_id — record which model each call ran under.

Adds ``token_usage.model_id`` (canonical id: catalog name for built-ins,
UUID for BYOM) so analytics can group spend by model. The partial index
mirrors ``token_usage_request_id_idx`` — it excludes the NULL rows that
pre-date the column.

Revision ID: 0015_token_usage_model_id
Revises: 0014_device_token_hash_index
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0015_token_usage_model_id"
down_revision: Union[str, None] = "0014_device_token_hash_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE token_usage ADD COLUMN model_id TEXT;")
    op.execute(
        'CREATE INDEX token_usage_model_ts_idx '
        'ON token_usage (model_id, "timestamp" DESC) '
        "WHERE model_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS token_usage_model_ts_idx;")
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS model_id;")
