"""0067 parsed files — the text parsed from a source file, reused when the same bytes are ingested again.

* ``parsed_files``: one row per user, file content (``content_sha256``) and
  ``parser_key``, the hash of everything that changes a parser's output
  (``docsgpt.parser.parse_cache.parser_key``: the parser classes, the OCR
  backend, engine, model, render DPI and languages, a parser version). A
  source ingest looks a file up before parsing it, so the same scanned PDF is
  OCR'd once however often it is ingested. ``content`` holds the parser's
  output (a string or a list of strings) and ``parser_metadata`` what the
  parser reported for the file; a large output is kept in the storage backend
  at ``storage_path`` instead, with ``content`` NULL. Only complete parses are
  stored. Rows are never shared across users. ``cleanup_parsed_files`` on beat
  deletes rows unused for ``PARSE_CACHE_TTL_DAYS``, by ``last_used_at``.

Idempotent both ways. Downgrade drops the table (its storage files stay; the
TTL task no longer runs, and they are only a cache).

Revision ID: 0067_parsed_files
Revises: 0066_source_sync_manifest
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0067_parsed_files"
down_revision: Union[str, None] = "0066_source_sync_manifest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ``parsed_files`` with its user FK and the ``ensure_user_exists`` trigger."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS parsed_files (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          text NOT NULL,
            content_sha256   text NOT NULL,
            parser_key       text NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            last_used_at     timestamptz NOT NULL DEFAULT now(),
            page_count       integer,
            billed_pages     integer,
            content          jsonb,
            parser_metadata  jsonb NOT NULL DEFAULT '{}'::jsonb,
            storage_path     text,
            CONSTRAINT parsed_files_user_content_parser_key UNIQUE (user_id, content_sha256, parser_key)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS parsed_files_last_used_idx ON parsed_files (last_used_at);")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'parsed_files_user_id_fk') THEN
                ALTER TABLE parsed_files ADD CONSTRAINT parsed_files_user_id_fk
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS parsed_files_ensure_user ON parsed_files")
    op.execute(
        "CREATE TRIGGER parsed_files_ensure_user BEFORE INSERT OR UPDATE OF user_id ON parsed_files "
        "FOR EACH ROW EXECUTE FUNCTION ensure_user_exists()"
    )


def downgrade() -> None:
    """Drop ``parsed_files`` (its trigger and constraints go with it)."""
    op.execute("DROP TABLE IF EXISTS parsed_files;")
