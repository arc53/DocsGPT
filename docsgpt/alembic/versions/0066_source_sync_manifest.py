"""0066 source sync manifest — what a file sync stored, so the next one uploads only changes.

* ``sources.sync_manifest``: for each file a ``sync`` of a file source
  stored, the path the client sent it under, the path it is stored at and the
  SHA-256 of its content, with the generation of the stored files and the
  generation the index was last built from (see
  ``docsgpt/api/user/sources/sync_manifest.py``). NULL until a sync runs.

No backfill: a source without a manifest has every file uploaded once by its
next sync. Idempotent both ways; downgrade drops the column.

Revision ID: 0066_source_sync_manifest
Revises: 0065_workspaces
"""

from alembic import op

revision = "0066_source_sync_manifest"
down_revision = "0065_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``sources.sync_manifest``."""
    op.execute("ALTER TABLE sources ADD COLUMN IF NOT EXISTS sync_manifest JSONB")


def downgrade() -> None:
    """Drop ``sources.sync_manifest``."""
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS sync_manifest")
