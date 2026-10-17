"""0033 quotas — admin-set usage limits and a per-call cost.

``quota_policies`` holds the limits an instance admin sets at three layers:
the instance default (``subject_id`` NULL), a team's per-member allowance
(``subject_id`` = ``teams.id``) and a single user's override (``subject_id`` =
the auth ``sub``). Each row carries a token budget and a USD budget; per
budget a row either sets a limit (0 blocks), marks it unlimited, or leaves
both empty to defer to the next layer. ``bucket`` narrows a row to chat without
an agent (``direct``) or traffic through an agent (``agent``); ``all`` covers both.

``subject_id`` is polymorphic, so there is no FK: an AFTER DELETE trigger on
``teams`` scrubs a deleted team's rows, and user rows follow the ``user_roles``
convention of never blocking user deletion.

``token_usage.cost`` is the USD cost of the call at write time (see
``docsgpt/pricing.py``); 0 for unpriced and bring-your-own models.
Idempotent both ways.

Revision ID: 0033_quotas
Revises: 0032_personal_access_tokens
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0033_quotas"
down_revision: Union[str, None] = "0032_personal_access_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS cost NUMERIC(12,8) NOT NULL DEFAULT 0;"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quota_policies (
            id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            scope           TEXT          NOT NULL CHECK (scope IN ('instance', 'team', 'user')),
            subject_id      TEXT,
            bucket          TEXT          NOT NULL DEFAULT 'all'
                                          CHECK (bucket IN ('all', 'direct', 'agent')),
            token_limit     BIGINT        CHECK (token_limit >= 0),
            token_unlimited BOOLEAN       NOT NULL DEFAULT false,
            cost_limit_usd  NUMERIC(12,4) CHECK (cost_limit_usd >= 0),
            cost_unlimited  BOOLEAN       NOT NULL DEFAULT false,
            enabled         BOOLEAN       NOT NULL DEFAULT true,
            note            TEXT,
            created_by      TEXT,
            updated_by      TEXT,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT quota_policies_subject_chk
                CHECK ((scope = 'instance') = (subject_id IS NULL)),
            CONSTRAINT quota_policies_token_chk
                CHECK (NOT (token_unlimited AND token_limit IS NOT NULL)),
            CONSTRAINT quota_policies_cost_chk
                CHECK (NOT (cost_unlimited AND cost_limit_usd IS NOT NULL))
        );
        """
    )
    # One row per (layer subject, bucket); the instance row's NULL subject folds to ''.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS quota_policies_subject_uidx "
        "ON quota_policies (scope, COALESCE(subject_id, ''), bucket);"
    )
    op.execute("DROP TRIGGER IF EXISTS quota_policies_set_updated_at ON quota_policies;")
    op.execute(
        """
        CREATE TRIGGER quota_policies_set_updated_at
        BEFORE UPDATE ON quota_policies
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cleanup_team_quota_policies() RETURNS trigger AS $$
        BEGIN
            DELETE FROM quota_policies WHERE scope = 'team' AND subject_id = OLD.id::text;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS teams_cleanup_quota_policies ON teams;")
    op.execute(
        """
        CREATE TRIGGER teams_cleanup_quota_policies
        AFTER DELETE ON teams
        FOR EACH ROW EXECUTE FUNCTION cleanup_team_quota_policies();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS teams_cleanup_quota_policies ON teams;")
    op.execute("DROP FUNCTION IF EXISTS cleanup_team_quota_policies();")
    op.execute("DROP TABLE IF EXISTS quota_policies;")
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS cost;")
