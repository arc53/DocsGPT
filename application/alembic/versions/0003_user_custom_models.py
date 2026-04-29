"""0003 user_custom_models — per-user OpenAI-compatible model registrations.

Revision ID: 0003_user_custom_models
Revises: 0002_app_metadata
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0003_user_custom_models"
down_revision: Union[str, None] = "0002_app_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_custom_models (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             TEXT NOT NULL,
            upstream_model_id   TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            description         TEXT NOT NULL DEFAULT '',
            base_url            TEXT NOT NULL,
            api_key_encrypted   TEXT NOT NULL,
            capabilities        JSONB NOT NULL DEFAULT '{}'::jsonb,
            enabled             BOOLEAN NOT NULL DEFAULT true,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX user_custom_models_user_id_idx "
        "ON user_custom_models (user_id);"
    )

    # Mirror the project-wide invariants set up in 0001_initial:
    #   * user_id FK with ON DELETE RESTRICT (deferrable),
    #   * ensure_user_exists() trigger so the parent users row autocreates,
    #   * set_updated_at() trigger.
    op.execute(
        "ALTER TABLE user_custom_models "
        "ADD CONSTRAINT user_custom_models_user_id_fk "
        "FOREIGN KEY (user_id) REFERENCES users(user_id) "
        "ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;"
    )
    op.execute(
        "CREATE TRIGGER user_custom_models_ensure_user "
        "BEFORE INSERT OR UPDATE OF user_id ON user_custom_models "
        "FOR EACH ROW EXECUTE FUNCTION ensure_user_exists();"
    )
    op.execute(
        "CREATE TRIGGER user_custom_models_set_updated_at "
        "BEFORE UPDATE ON user_custom_models "
        "FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) "
        "EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_custom_models;")
