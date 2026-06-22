"""0023 wiki pages — authoritative storage for the LLM-editable wiki source.

Adds ``wiki_pages`` (page = unit), source-scoped (team-shareable) and the
authoritative store for a ``config.kind="wiki"`` source. The vector store is a
derived index re-embedded asynchronously per page; ``embed_status`` tracks that
freshness. ``UNIQUE(source_id, path)`` makes a page addressable like a file;
the ``text_pattern_ops`` index backs prefix listing of the virtual tree.

No new Postgres extensions (keeps it Neon/DBngin-portable).

Revision ID: 0023_wiki_pages
Revises: 0022_source_config
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0023_wiki_pages"
down_revision: Union[str, None] = "0022_source_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wiki_pages (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id    UUID        NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            path         TEXT        NOT NULL,
            title        TEXT,
            content      TEXT        NOT NULL,
            token_count  INTEGER,
            version      INTEGER     NOT NULL DEFAULT 1,
            content_hash TEXT,
            embed_status TEXT        NOT NULL DEFAULT 'pending',
            updated_by   TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS wiki_pages_source_path_uidx "
        "ON wiki_pages (source_id, path);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS wiki_pages_source_path_prefix_idx "
        "ON wiki_pages (source_id, path text_pattern_ops);"
    )
    op.execute("DROP TRIGGER IF EXISTS wiki_pages_set_updated_at ON wiki_pages;")
    op.execute(
        """
        CREATE TRIGGER wiki_pages_set_updated_at
        BEFORE UPDATE ON wiki_pages
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wiki_pages;")
