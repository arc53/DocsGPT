"""0020 user roles — admin/user RBAC grant table.

``user_roles`` records elevated role grants only; the ``user`` role is implicit
(every authenticated principal has it without a row). A grant is keyed by
``(user_id, role, source)`` so a manual grant and an OIDC-group-derived grant
for the same user coexist and revoke independently. ``user_id`` is the auth
``sub`` (the TEXT business key used everywhere else, not ``users.id``); no FK or
trigger, mirroring ``auth_events`` — grants may legitimately precede user
provisioning, and we don't want ``ON DELETE RESTRICT`` blocking user deletion.

The ``CHECK (role IN ('admin'))`` is the role catalog — there is no separate
``roles`` table. Widen the check when new roles are introduced. The PK indexes
``user_id`` as its leading column, so ``WHERE user_id = :sub`` lookups are a
single index probe with no extra index.

Revision ID: 0020_user_roles
Revises: 0019_agent_slug
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0020_user_roles"
down_revision: Union[str, None] = "0019_agent_slug"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS keeps the migration idempotent across partial/out-of-band
    # schema states, matching the convention used by the surrounding migrations.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id    TEXT        NOT NULL,
            role       TEXT        NOT NULL CHECK (role IN ('admin')),
            source     TEXT        NOT NULL DEFAULT 'manual'
                                   CHECK (source IN ('manual', 'oidc_group')),
            granted_by TEXT,
            granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, role, source)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_roles;")
