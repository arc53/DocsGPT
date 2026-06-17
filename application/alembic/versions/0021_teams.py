"""0021 teams — multi-team membership, team-scoped roles, resource sharing.

Adds the whole Teams feature in one migration:

* ``teams`` — a team. ``owner_id`` is the creator's auth ``sub`` and the durable
  "who can delete the team" anchor. No FK/trigger on it (mirroring ``user_roles``
  / ``auth_events``): an ``ON DELETE RESTRICT`` FK would block user deletion
  (SCIM/GDPR) and force an owner-reassignment dance on every delete.
* ``team_members`` — membership + team-scoped role grant, field-for-field on
  ``user_roles``. ``(team_id, user_id, role, source)`` PK so a manual grant and a
  future IdP-derived grant coexist and revoke independently. The ``source`` CHECK
  already carries ``oidc_group``/``scim`` so those phases need no migration.
* ``team_resource_grants`` — one polymorphic share table covering all four
  shareable resource types. ``owner_id`` is denormalised owner-at-share-time so
  visibility queries never re-join the resource table. ``target_user_id`` is NULL
  for a whole-team share or a member's ``sub`` for a per-member share; the dedup
  index is functional over ``COALESCE(target_user_id, '')`` so a whole-team grant
  and any number of per-member grants for the same (team, resource) coexist.
  Sharing is additive visibility, never ownership transfer.

Grant rows have no cross-table FK (the resource_id is polymorphic), so an
``AFTER DELETE`` trigger on each resource table scrubs dangling grants — covering
the non-route delete paths (reconciler / sync) that bypass app cleanup.

Also adds ``users.email`` (populated from the OIDC email claim at login) so a
team admin can add a member by email instead of pasting a raw ``sub``.

Revision ID: 0021_teams
Revises: 0020_user_roles
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0021_teams"
down_revision: Union[str, None] = "0020_user_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RESOURCE_TABLES = ("agents", "sources", "prompts", "user_tools")
_RESOURCE_TYPES = {
    "agents": "agent",
    "sources": "source",
    "prompts": "prompt",
    "user_tools": "tool",
}


def upgrade() -> None:
    # --- teams ---------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name        TEXT        NOT NULL,
            slug        CITEXT      NOT NULL,
            description TEXT,
            owner_id    TEXT        NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS teams_slug_uidx ON teams (slug);")
    op.execute("CREATE INDEX IF NOT EXISTS teams_owner_idx ON teams (owner_id);")
    # Reuse the shared set_updated_at() trigger fn defined in 0001.
    op.execute("DROP TRIGGER IF EXISTS teams_set_updated_at ON teams;")
    op.execute(
        """
        CREATE TRIGGER teams_set_updated_at
        BEFORE UPDATE ON teams
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    # --- team_members --------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS team_members (
            team_id    UUID        NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            user_id    TEXT        NOT NULL,
            role       TEXT        NOT NULL
                                   CHECK (role IN ('team_admin', 'team_member')),
            source     TEXT        NOT NULL DEFAULT 'manual'
                                   CHECK (source IN ('manual', 'oidc_group', 'scim')),
            granted_by TEXT,
            granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (team_id, user_id, role, source)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS team_members_user_idx ON team_members (user_id);"
    )

    # --- team_resource_grants ------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS team_resource_grants (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id        UUID        NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            resource_type  TEXT        NOT NULL
                                       CHECK (resource_type IN ('agent', 'source', 'prompt', 'tool')),
            resource_id    UUID        NOT NULL,
            owner_id       TEXT        NOT NULL,
            access_level   TEXT        NOT NULL DEFAULT 'viewer'
                                       CHECK (access_level IN ('viewer', 'editor')),
            target_user_id TEXT,
            granted_by     TEXT        NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    # Functional dedup: whole-team (target NULL → '') and each per-member grant
    # are distinct keys.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS team_resource_grants_dedup_uidx
        ON team_resource_grants
            (team_id, resource_type, resource_id, COALESCE(target_user_id, ''));
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS team_resource_grants_team_type_idx
        ON team_resource_grants (team_id, resource_type);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS team_resource_grants_resource_idx
        ON team_resource_grants (resource_type, resource_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS team_resource_grants_target_idx
        ON team_resource_grants (target_user_id)
        WHERE target_user_id IS NOT NULL;
        """
    )

    # --- dangling-grant cleanup ---------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cleanup_team_resource_grants() RETURNS trigger AS $$
        BEGIN
            DELETE FROM team_resource_grants
            WHERE resource_type = TG_ARGV[0] AND resource_id = OLD.id;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in _RESOURCE_TABLES:
        trig = f"{table}_cleanup_team_grants"
        op.execute(f"DROP TRIGGER IF EXISTS {trig} ON {table};")
        op.execute(
            f"CREATE TRIGGER {trig} AFTER DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION cleanup_team_resource_grants('{_RESOURCE_TYPES[table]}');"
        )

    # --- users.email (add-member-by-email) -----------------------------------
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;")
    op.execute(
        "CREATE INDEX IF NOT EXISTS users_email_lower_idx ON users (lower(email));"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_email_lower_idx;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email;")
    for table in _RESOURCE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_cleanup_team_grants ON {table};")
    op.execute("DROP FUNCTION IF EXISTS cleanup_team_resource_grants();")
    op.execute("DROP TABLE IF EXISTS team_resource_grants;")
    op.execute("DROP TABLE IF EXISTS team_members;")
    op.execute("DROP TABLE IF EXISTS teams;")
