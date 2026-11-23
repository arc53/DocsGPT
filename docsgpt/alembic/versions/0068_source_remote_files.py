"""0068 source remote files — what a source's last sync indexed, so the next one changes only the rest.

* ``sources.remote_files``: the manifest of the files the index holds (see
  ``docsgpt/parser/incremental.py``). For a connector source, each file's
  provider id, path, version and link; for a remote source (GitHub, a crawl,
  S3...), each file's path and a hash of its content. Both carry the
  settings they were built under. NULL until an ingest writes one; a source
  without one has its next sync rebuild the index once, and write it.

Kept apart from ``remote_data``: a large selection's manifest runs to
megabytes, and ``remote_data`` is read with every source listing.

Idempotent both ways; downgrade drops the column.

Revision ID: 0068_source_remote_files
Revises: 0067_parsed_files
"""

from alembic import op

revision = "0068_source_remote_files"
down_revision = "0067_parsed_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``sources.remote_files``."""
    op.execute("ALTER TABLE sources ADD COLUMN IF NOT EXISTS remote_files JSONB")


def downgrade() -> None:
    """Drop ``sources.remote_files``."""
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS remote_files")
