"""0025 artifacts — append-only artifact identity + version store.

Adds the long-anticipated ``artifacts`` entity referenced by the schema header
in ``models.py`` but never built. Two tables:

* ``artifacts`` — one identity row per logical artifact. The stable ``id`` is the
  handle passed around (chat/workflow ``state``/message bodies carry only this
  reference, never bytes). ``current_version`` mirrors
  ``workflows.current_graph_version`` (atomic increment on each new version).
  Authz is parent-derived: whoever can reach the ``conversation_id`` (chat) or
  ``workflow_run_id`` (run) can reach its artifacts, so a CHECK requires at least
  one parent. ``user_id`` is kept for ownership/quota only; ``team_id`` is a
  nullable forward-compat hook for the in-flight Teams work (no FK, matching how
  ``teams`` itself leaves owner/member columns FK-free).
* ``artifact_versions`` — append-only, never mutated. Each edit appends a row and
  bumps ``artifacts.current_version``. ``UNIQUE(artifact_id, version)`` enforces
  monotonic, gap-checkable versions. ``storage_path`` is the ``BaseStorage`` key
  (NULL when the version is spec-only). Pass-by-reference: bytes live in storage,
  only metadata + the key live here.

Revision ID: 0025_artifacts
Revises: 0024_wiki_pages_updated_via
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0025_artifacts"
down_revision: Union[str, None] = "0024_wiki_pages_updated_via"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- artifacts -----------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT        NOT NULL,
            conversation_id UUID,
            workflow_run_id UUID,
            team_id         UUID,
            message_id      UUID,
            kind            TEXT        NOT NULL,
            title           TEXT,
            metadata        JSONB,
            current_version INTEGER     NOT NULL DEFAULT 1,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT artifacts_parent_present_check
                CHECK (conversation_id IS NOT NULL OR workflow_run_id IS NOT NULL)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS artifacts_user_idx ON artifacts (user_id);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS artifacts_conversation_idx "
        "ON artifacts (conversation_id) WHERE conversation_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS artifacts_workflow_run_idx "
        "ON artifacts (workflow_run_id) WHERE workflow_run_id IS NOT NULL;"
    )
    # Reuse the shared set_updated_at() trigger fn defined in 0001.
    op.execute("DROP TRIGGER IF EXISTS artifacts_set_updated_at ON artifacts;")
    op.execute(
        """
        CREATE TRIGGER artifacts_set_updated_at
        BEFORE UPDATE ON artifacts
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # --- artifact_versions ---------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_versions (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_id  UUID        NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
            version      INTEGER     NOT NULL,
            mime_type    TEXT,
            filename     TEXT,
            storage_path TEXT,
            size         BIGINT,
            sha256       TEXT,
            spec         JSONB,
            preview_text TEXT,
            produced_by  JSONB,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT artifact_versions_artifact_version_uidx
                UNIQUE (artifact_id, version)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS artifact_versions_artifact_idx "
        "ON artifact_versions (artifact_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS artifact_versions_artifact_idx;")
    op.execute("DROP TABLE IF EXISTS artifact_versions;")
    op.execute("DROP TRIGGER IF EXISTS artifacts_set_updated_at ON artifacts;")
    op.execute("DROP INDEX IF EXISTS artifacts_workflow_run_idx;")
    op.execute("DROP INDEX IF EXISTS artifacts_conversation_idx;")
    op.execute("DROP INDEX IF EXISTS artifacts_user_idx;")
    op.execute("DROP TABLE IF EXISTS artifacts;")
