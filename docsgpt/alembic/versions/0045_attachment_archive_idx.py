"""0045 attachment archive index — find zips whose members are still parsing.

A zip attachment's members parse as their own worker tasks, and the zip
completes when the last one records its outcome. A member whose task is
lost would leave the zip processing forever, so the reconciler looks for
zips still processing every tick. This partial index holds only those rows
(usually none), so the sweep never scans the attachments table.

Built ``CONCURRENTLY`` in an autocommit block (following 0028) so the build
never blocks writes to ``attachments``; an INVALID leftover of a cancelled
build is dropped first, since ``IF NOT EXISTS`` would otherwise keep it.

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

_INDEX = "attachments_archive_processing_idx"


def _drop_if_invalid(name: str) -> None:
    """Drop ``name`` when a previous concurrent build left it INVALID.

    Args:
        name: The index name.
    """
    invalid = (
        op.get_bind()
        .exec_driver_sql(f"SELECT NOT indisvalid FROM pg_index WHERE indexrelid = to_regclass('{name}')")
        .scalar()
    )
    if invalid:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name};")


def upgrade() -> None:
    # CONCURRENTLY can't run inside a transaction.
    with op.get_context().autocommit_block():
        _drop_if_invalid(_INDEX)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON attachments (created_at) WHERE (metadata->'archive'->>'status') = 'processing';"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX};")
