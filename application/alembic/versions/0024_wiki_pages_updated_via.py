"""0024 wiki pages updated_via — provenance of the last page write.

Adds a nullable ``updated_via`` column recording which channel last wrote a
page ("agent" via the WikiTool/conversion, "human" via the edit endpoint) so the
viewer can stamp each page's provenance alongside ``updated_by`` / ``updated_at``
/ ``version``.

Revision ID: 0024_wiki_pages_updated_via
Revises: 0023_wiki_pages
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0024_wiki_pages_updated_via"
down_revision: Union[str, None] = "0023_wiki_pages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS updated_via TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE wiki_pages DROP COLUMN IF EXISTS updated_via;")
