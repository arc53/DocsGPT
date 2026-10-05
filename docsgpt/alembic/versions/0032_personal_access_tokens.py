"""0032 personal access tokens — scoped, user-level API credentials.

A personal access token (PAT) authenticates its owner against the management
API for CLI and CI/CD use. Only the SHA-256 of the secret is stored, mirroring
``devices.token_hash``: the plaintext is shown once at creation and a database
leak cannot reconstruct it. ``token_prefix`` keeps the first characters so a
user can tell their tokens apart in the UI.

``scopes`` is the server-side grant list (never read from the credential
itself). ``resource_filter`` optionally narrows a resource family to specific
ids, e.g. ``{"agents": ["<uuid>"]}``; an absent family is unrestricted within
the token's scopes. ``expires_at`` is NULL only when the operator allows
non-expiring tokens. Regenerating a token swaps its secret in place and stamps
``regenerated_at``; the row, its name, scopes and restrictions stay.

``user_id`` is the auth ``sub``; no FK or trigger, mirroring ``devices`` and
``user_roles`` so a token row never blocks user deletion.

Revision ID: 0032_personal_access_tokens
Revises: 0031_token_usage_cache_tokens
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0032_personal_access_tokens"
down_revision: Union[str, None] = "0031_token_usage_cache_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS personal_access_tokens (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT        NOT NULL,
            name            TEXT        NOT NULL,
            token_hash      TEXT        NOT NULL,
            token_prefix    TEXT        NOT NULL,
            scopes          TEXT[]      NOT NULL DEFAULT '{}',
            resource_filter JSONB       NOT NULL DEFAULT '{}'::jsonb,
            status          TEXT        NOT NULL DEFAULT 'active'
                                        CHECK (status IN ('active', 'revoked')),
            expires_at      TIMESTAMPTZ,
            last_used_at    TIMESTAMPTZ,
            last_used_ip    TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            regenerated_at  TIMESTAMPTZ,
            revoked_at      TIMESTAMPTZ,
            revoke_reason   TEXT
        );
        """
    )
    # Looked up on every PAT-authenticated request.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS personal_access_tokens_hash_uidx "
        "ON personal_access_tokens(token_hash);"
    )
    # Names are unique among a user's live tokens; a revoked name can be reused.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS personal_access_tokens_user_name_uidx "
        "ON personal_access_tokens(user_id, name) WHERE status = 'active';"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS personal_access_tokens_user_idx "
        "ON personal_access_tokens(user_id, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS personal_access_tokens;")
