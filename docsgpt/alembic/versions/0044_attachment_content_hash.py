"""0044 attachment content hash — find a user's earlier upload of the same bytes.

The attachment worker records a sha256 of each upload's original bytes.
``attachments.content_hash`` holds it, with an index on
``(user_id, content_hash)``, so an upload of bytes the user already sent (a
/v1 client re-sends every file each turn) reuses the parsed text instead of
parsing again.

No backfill: nothing wrote a content hash before this column, so existing
rows have none to copy, and a full-table UPDATE would lock ``attachments``
for nothing. Adding a nullable column without a default is a catalog-only
change. The index is built ``CONCURRENTLY`` in an autocommit block
(following 0028): a plain CREATE INDEX would block writes to the table for
the whole build. A cancelled concurrent build leaves an INVALID index that
``IF NOT EXISTS`` would skip forever, so such a leftover is dropped first.

Idempotent both ways.

Revision ID: 0044_attachment_content_hash
Revises: 0043_wiki_outside_edits
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0044_attachment_content_hash"
down_revision: Union[str, None] = "0043_wiki_outside_edits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "attachments_user_content_hash_idx"


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
    op.execute("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS content_hash TEXT;")
    # CONCURRENTLY can't run inside a transaction.
    with op.get_context().autocommit_block():
        _drop_if_invalid(_INDEX)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON attachments (user_id, content_hash) WHERE content_hash IS NOT NULL;"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX};")
    op.execute("ALTER TABLE attachments DROP COLUMN IF EXISTS content_hash;")
