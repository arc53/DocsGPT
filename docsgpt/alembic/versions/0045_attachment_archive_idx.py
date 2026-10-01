"""0045 attachment archive index — find zips whose members are still parsing.

A zip attachment's members parse as their own worker tasks, and the zip
completes when the last one records its outcome. A member whose task is
lost would leave the zip processing forever, so the reconciler looks for
zips still processing every tick. This partial index holds only those rows
(usually none), so the sweep never scans the attachments table.

Idempotent both ways.

Revision ID: 0045_attachment_archive_idx
Revises: 0044_attachment_content_hash
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0045_attachment_archive_idx"
down_revision: Union[str, None] = "0044_attachment_content_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS attachments_archive_processing_idx "
        "ON attachments (created_at) WHERE (metadata->'archive'->>'status') = 'processing';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS attachments_archive_processing_idx;")
