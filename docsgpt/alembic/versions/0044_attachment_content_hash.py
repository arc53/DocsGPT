"""0044 attachment content hash — find a user's earlier upload of the same bytes.

The attachment worker records a sha256 of each upload's original bytes in
``metadata.content_hash``. ``attachments.content_hash`` makes it a column
with an index on ``(user_id, content_hash)``, so an upload of bytes the user
already sent (a /v1 client re-sends every file each turn) reuses the parsed
text instead of parsing again. Existing rows are backfilled from metadata
where it holds a well-formed sha256.

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


def upgrade() -> None:
    op.execute("ALTER TABLE attachments ADD COLUMN IF NOT EXISTS content_hash TEXT;")
    op.execute(
        """
        UPDATE attachments
        SET content_hash = metadata->>'content_hash'
        WHERE content_hash IS NULL
          AND jsonb_typeof(metadata) = 'object'
          AND metadata->>'content_hash' ~ '^[0-9a-f]{64}$';
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS attachments_user_content_hash_idx "
        "ON attachments (user_id, content_hash) WHERE content_hash IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS attachments_user_content_hash_idx;")
    op.execute("ALTER TABLE attachments DROP COLUMN IF EXISTS content_hash;")
