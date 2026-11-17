"""0065 workspaces — team principals, three team roles, provenance and the conversation workspace.

* ``users.kind`` (``user``, ``team`` or ``system``) and ``users.team_id``. A
  team's items are owned by its principal row, ``'__team__' || teams.id``, one
  per team; existing teams get theirs here and ``__system__`` becomes
  ``system``. ``users_team_principal_chk`` ties the id to the team and keeps
  the prefix off every other row, so the ``ensure_user_exists`` trigger can't
  mint a principal; the trigger now only inserts ids that have no row, so a
  write under an existing principal passes. ``users.team_id`` is ``ON DELETE
  RESTRICT``: a team can't be deleted while its principal row exists.
* Team roles: ``team_member`` becomes ``team_viewer`` (dropped where the same
  person holds ``team_admin`` from the same source); the stored roles are
  ``team_admin``, ``team_editor`` and ``team_viewer``. ``team_members`` and
  ``team_resource_grants.owner_id`` refuse principal ids: a principal is never
  a member, and a team's own items are never granted.
* ``created_by`` (a person's id, no FK) on agents, sources, user_tools,
  prompts, workflows and folders, backfilled from ``user_id`` without moving
  ``updated_at``; on insert it defaults to a person owner (never a principal).
* ``agents.access_payer_id``: who pays for outside traffic (key, link,
  webhook) on a team agent; always a person. It is bookkeeping for
  ``agents_set_updated_at``.
* ``conversations.team_id`` (NULL = Personal), ``ON DELETE CASCADE``, and the
  sidebar index gains it. ``conversations_team_idx`` (``team_id, id``, team
  rows only) serves a team's chat export and the cascade when a team goes.
* ``schedule_runs.error_type`` also allows ``owner_inactive``, and the reasons
  a run is skipped while its payer can't pay: ``payer_out_of_allowance``,
  ``payer_left`` and ``no_payer``.
* ``token_usage.team_id`` (the workspace a model call was made in, NULL =
  Personal; no FK, like ``agent_id``, so a deleted team's rows keep their id)
  and ``token_usage.run_kind`` (``chat``, ``schedule``, ``published``,
  ``knowledge``, ``monitor`` or ``drafter``; NULL on rows written before it).
  ``token_usage_team_ts_idx`` serves a team's usage report. The two columns
  are metadata-only; the index is a plain CREATE INDEX, which reads the whole
  table once and holds off writes to it while it builds.
* ``teams.outside_policy`` (``admins``, ``editors`` or ``locked``; default
  ``admins``, metadata-only): who may take the team's items outside the team.
* ``team_item_shares``: a team's agent, source, tool or prompt shared with a
  whole other team (``owner_team_id`` shares into ``team_id``). Not a
  ``team_resource_grants`` row: every grant reader assumes a person's item and
  pauses a grant when its owner leaves, while a team's share outlives the
  person who made it. ``shared_by`` is a person. Both teams cascade; the
  ``cleanup_team_item_shares`` triggers drop an item's shares when the item is
  deleted or changes owner (a move out of the team).

Idempotent both ways. Downgrade refuses while any row still belongs to a
principal; otherwise it turns ``team_editor``/``team_viewer`` back into
``team_member`` and deletes the principal rows.

Revision ID: 0065_workspaces
Revises: 0064_workspace_folders
"""

from alembic import op

revision = "0065_workspaces"
down_revision = "0064_workspace_folders"
branch_labels = None
depends_on = None

#: The prefix of a team principal's ``users.user_id`` (``docsgpt/workspaces/principal.py``).
_PREFIX = "__team__"

#: Tables that record who created each row.
_PROVENANCE_TABLES = ("agents", "sources", "user_tools", "prompts", "workflows", "folders")

#: Bookkeeping agent columns the ``agents_set_updated_at`` trigger skips: 0064's, then with the payer.
_BOOKKEEPING = (
    "ARRAY['updated_at', 'last_used_at', 'key', 'incoming_webhook_token', "
    "'shared', 'shared_token', 'shared_metadata', 'slug']"
)
_BOOKKEEPING_WITH_PAYER = (
    "ARRAY['updated_at', 'last_used_at', 'key', 'incoming_webhook_token', "
    "'shared', 'shared_token', 'shared_metadata', 'slug', 'access_payer_id']"
)

#: Run error types before (0063) and after this revision.
_RUN_ERRORS = (
    "'auth_expired', 'tool_not_allowed', 'budget_exceeded', "
    "'timeout', 'agent_error', 'internal', 'missed', 'overlap', "
    "'stream_error', 'empty_output', 'cannot_complete'"
)
_RUN_ERRORS_WITH_OWNER = _RUN_ERRORS + ", 'owner_inactive'"
#: The reasons a run is skipped while its payer can't pay for it.
_PAYER_PAUSES = "'payer_out_of_allowance', 'payer_left', 'no_payer'"
_RUN_ERRORS_WITH_PAYER = _RUN_ERRORS_WITH_OWNER + ", " + _PAYER_PAUSES

#: The outside policies of a team (``docsgpt/workspaces/outside.py::POLICIES``).
_OUTSIDE_POLICIES = "'admins', 'editors', 'locked'"

#: The item tables a team may share with another team, and the kind each holds.
_SHAREABLE = {"agents": "agent", "sources": "source", "user_tools": "tool", "prompts": "prompt"}

#: What a model call was part of (``docsgpt/quotas/payer.py::RUN_KINDS``).
_RUN_KINDS = "'chat', 'schedule', 'published', 'knowledge', 'monitor', 'drafter'"

#: The ``ensure_user_exists`` body of 0001, and the one that leaves existing rows alone.
_ENSURE_USER_ANY = """
        CREATE OR REPLACE FUNCTION ensure_user_exists() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.user_id IS NOT NULL THEN
                INSERT INTO users (user_id) VALUES (NEW.user_id)
                ON CONFLICT (user_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$;
"""
# A CHECK is evaluated before ON CONFLICT, so the insert must not even be tried for an existing
# principal; a missing one is still inserted as a person and refused by users_team_principal_chk.
_ENSURE_USER_NEW = """
        CREATE OR REPLACE FUNCTION ensure_user_exists() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.user_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM users WHERE user_id = NEW.user_id) THEN
                INSERT INTO users (user_id) VALUES (NEW.user_id)
                ON CONFLICT (user_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$;
"""


def _content_trigger(bookkeeping: str) -> str:
    """The ``agents_set_updated_at`` trigger that ignores ``bookkeeping`` columns."""
    return (
        "CREATE TRIGGER agents_set_updated_at BEFORE UPDATE ON agents FOR EACH ROW "
        f"WHEN ((to_jsonb(OLD) - {bookkeeping}) IS DISTINCT FROM (to_jsonb(NEW) - {bookkeeping})) "
        "EXECUTE FUNCTION set_updated_at()"
    )


def _add_constraint(table: str, name: str, definition: str) -> None:
    """Replace ``name`` on ``table`` with ``definition`` (idempotent)."""
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")


def _set_updated_at_triggers(table: str, enable: bool) -> None:
    """Switch ``<table>_set_updated_at`` off or on, when the table has it."""
    action = "ENABLE" if enable else "DISABLE"
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = '{table}_set_updated_at'
                       AND tgrelid = '{table}'::regclass) THEN
                ALTER TABLE {table} {action} TRIGGER {table}_set_updated_at;
            END IF;
        END $$;
        """
    )


def _upgrade_outside() -> None:
    """Add the outside policy and the table of a team's shares with other teams."""
    op.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS outside_policy TEXT NOT NULL DEFAULT 'admins'")
    _add_constraint("teams", "teams_outside_policy_chk", f"CHECK (outside_policy IN ({_OUTSIDE_POLICIES}))")
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS team_item_shares (
            id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_team_id UUID        NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            team_id       UUID        NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            resource_type TEXT        NOT NULL,
            resource_id   UUID        NOT NULL,
            shared_by     TEXT        NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT team_item_shares_type_chk CHECK (resource_type IN ('agent', 'source', 'tool', 'prompt')),
            CONSTRAINT team_item_shares_other_team_chk CHECK (owner_team_id <> team_id),
            CONSTRAINT team_item_shares_person_chk CHECK (left(shared_by, 8) <> '{_PREFIX}')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS team_item_shares_team_resource_uidx "
        "ON team_item_shares (team_id, resource_type, resource_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS team_item_shares_resource_idx ON team_item_shares (resource_type, resource_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS team_item_shares_owner_team_idx ON team_item_shares (owner_team_id)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cleanup_team_item_shares() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM team_item_shares WHERE resource_type = TG_ARGV[0] AND resource_id = OLD.id;
            RETURN NULL;
        END;
        $$;
        """
    )
    for table, kind in _SHAREABLE.items():
        op.execute(f"DROP TRIGGER IF EXISTS {table}_cleanup_team_item_shares ON {table}")
        op.execute(
            f"CREATE TRIGGER {table}_cleanup_team_item_shares AFTER DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION cleanup_team_item_shares('{kind}')"
        )
        # A move out of the team re-owns the row; what the team shared of it ends there.
        op.execute(f"DROP TRIGGER IF EXISTS {table}_reown_team_item_shares ON {table}")
        op.execute(
            f"CREATE TRIGGER {table}_reown_team_item_shares AFTER UPDATE OF user_id ON {table} "
            "FOR EACH ROW WHEN (OLD.user_id IS DISTINCT FROM NEW.user_id) "
            f"EXECUTE FUNCTION cleanup_team_item_shares('{kind}')"
        )


def _downgrade_outside() -> None:
    """Drop the shares with other teams and the outside policy."""
    for table in _SHAREABLE:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_reown_team_item_shares ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_cleanup_team_item_shares ON {table}")
    op.execute("DROP FUNCTION IF EXISTS cleanup_team_item_shares()")
    op.execute("DROP TABLE IF EXISTS team_item_shares")
    op.execute("ALTER TABLE teams DROP CONSTRAINT IF EXISTS teams_outside_policy_chk")
    op.execute("ALTER TABLE teams DROP COLUMN IF EXISTS outside_policy")


def upgrade() -> None:
    """Add team principals and roles, provenance, the access payer, the chat workspace and usage attribution."""
    # Principals.
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'user'")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE RESTRICT")
    op.execute(
        f"""
        DO $$
        DECLARE forged text;
        BEGIN
            SELECT user_id INTO forged FROM users WHERE left(user_id, 8) = '{_PREFIX}' AND kind <> 'team' LIMIT 1;
            IF forged IS NOT NULL THEN
                RAISE EXCEPTION 'Cannot upgrade to 0065: user % uses the reserved prefix {_PREFIX}. '
                    'Rename or remove that account first.', forged;
            END IF;
        END $$;
        """
    )
    op.execute("UPDATE users SET kind = 'system' WHERE user_id IN ('__system__', 'system') AND kind = 'user'")
    _add_constraint("users", "users_kind_chk", "CHECK (kind IN ('user', 'team', 'system'))")
    _add_constraint(
        "users",
        "users_team_principal_chk",
        f"""CHECK (
            ((kind = 'team') = (team_id IS NOT NULL))
            AND (kind <> 'team' OR user_id = '{_PREFIX}' || team_id::text)
            AND (kind = 'team' OR left(user_id, 8) <> '{_PREFIX}'))""",
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_team_id_uidx ON users (team_id) WHERE team_id IS NOT NULL")
    op.execute(
        f"INSERT INTO users (user_id, kind, team_id) SELECT '{_PREFIX}' || id::text, 'team', id FROM teams "
        "ON CONFLICT (user_id) DO NOTHING"
    )
    op.execute(_ENSURE_USER_NEW)

    # Team roles: the owner stays teams.owner_id (with its admin row); member collapses, then is renamed.
    op.execute("ALTER TABLE team_members DROP CONSTRAINT IF EXISTS team_members_role_check")
    op.execute(
        """
        DELETE FROM team_members m WHERE m.role = 'team_member' AND EXISTS (
            SELECT 1 FROM team_members a WHERE a.team_id = m.team_id AND a.user_id = m.user_id
               AND a.source = m.source AND a.role = 'team_admin')
        """
    )
    op.execute("UPDATE team_members SET role = 'team_viewer' WHERE role = 'team_member'")
    op.execute(
        "ALTER TABLE team_members ADD CONSTRAINT team_members_role_check "
        "CHECK (role IN ('team_admin', 'team_editor', 'team_viewer'))"
    )
    _add_constraint("team_members", "team_members_person_chk", f"CHECK (left(user_id, 8) <> '{_PREFIX}')")
    _add_constraint(
        "team_resource_grants", "team_resource_grants_personal_owner_chk", f"CHECK (left(owner_id, 8) <> '{_PREFIX}')"
    )

    # Provenance: who created the row; a person, never a principal.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION fill_created_by() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.created_by IS NULL AND left(NEW.user_id, 8) <> '{_PREFIX}' THEN
                NEW.created_by := NEW.user_id;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    for table in _PROVENANCE_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_by TEXT")
        # The backfill isn't an edit: keep updated_at as it was.
        _set_updated_at_triggers(table, enable=False)
        op.execute(
            f"UPDATE {table} SET created_by = user_id "
            f"WHERE created_by IS NULL AND left(user_id, 8) <> '{_PREFIX}'"
        )
        _set_updated_at_triggers(table, enable=True)
        op.execute(f"DROP TRIGGER IF EXISTS {table}_fill_created_by ON {table}")
        op.execute(
            f"CREATE TRIGGER {table}_fill_created_by BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION fill_created_by()"
        )

    # Who pays for a team agent's outside traffic; changing it is not an edit of the agent.
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS access_payer_id TEXT")
    _add_constraint(
        "agents",
        "agents_access_payer_person_chk",
        f"CHECK (access_payer_id IS NULL OR left(access_payer_id, 8) <> '{_PREFIX}')",
    )
    op.execute("DROP TRIGGER IF EXISTS agents_set_updated_at ON agents")
    op.execute(_content_trigger(_BOOKKEEPING_WITH_PAYER))

    # A conversation's workspace (NULL = Personal); an empty team's chats go with it.
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversations_user_ws_listed_idx "
        "ON conversations (user_id, team_id, date DESC) WHERE visibility = 'listed'"
    )
    op.execute("DROP INDEX IF EXISTS conversations_user_listed_idx")
    # A team's chats by team: the export pages through them by id, and deleting a team cascades to them.
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversations_team_idx ON conversations (team_id, id) WHERE team_id IS NOT NULL"
    )

    # A run skipped because its owner or payer was deactivated, or its payer can't pay, says so.
    _add_constraint(
        "schedule_runs",
        "schedule_runs_error_type_chk",
        f"CHECK (error_type IS NULL OR error_type IN ({_RUN_ERRORS_WITH_PAYER}))",
    )

    # Which workspace and which kind of run each model call was made for.
    op.execute("ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS team_id UUID")
    op.execute("ALTER TABLE token_usage ADD COLUMN IF NOT EXISTS run_kind TEXT")
    _add_constraint(
        "token_usage", "token_usage_run_kind_chk", f"CHECK (run_kind IS NULL OR run_kind IN ({_RUN_KINDS}))"
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS token_usage_team_ts_idx ON token_usage (team_id, "timestamp" DESC) '
        "WHERE team_id IS NOT NULL"
    )

    # Who may take the team's items outside, and its shares with other teams.
    _upgrade_outside()


def downgrade() -> None:
    """Refuse while a principal owns rows; otherwise drop principals, fold roles back and drop the columns."""
    op.execute(
        f"""
        DO $$
        DECLARE
            fk record;
            n bigint;
            held text := '';
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'users' AND column_name = 'kind') THEN
                RETURN;
            END IF;
            FOR fk IN
                SELECT c.conrelid::regclass::text AS tbl, a.attname AS col
                FROM pg_constraint c
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass
                  AND array_length(c.conkey, 1) = 1
                ORDER BY 1
            LOOP
                EXECUTE format('SELECT count(*) FROM %s WHERE left(%I, 8) = %L', fk.tbl, fk.col, '{_PREFIX}')
                    INTO n;
                IF n > 0 THEN
                    held := held || format(' %s=%s', fk.tbl, n);
                END IF;
            END LOOP;
            IF held <> '' THEN
                RAISE EXCEPTION 'Cannot downgrade 0065: team workspaces still own rows (%). '
                    'Move or delete them first.', btrim(held);
            END IF;
        END $$;
        """
    )

    _downgrade_outside()

    op.execute("DROP INDEX IF EXISTS token_usage_team_ts_idx")
    op.execute("ALTER TABLE token_usage DROP CONSTRAINT IF EXISTS token_usage_run_kind_chk")
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS run_kind")
    op.execute("ALTER TABLE token_usage DROP COLUMN IF EXISTS team_id")

    # A skipped run keeps its reason in ``error``; the type goes back to unset.
    op.execute(f"UPDATE schedule_runs SET error_type = NULL WHERE error_type IN ({_PAYER_PAUSES})")
    _add_constraint(
        "schedule_runs",
        "schedule_runs_error_type_chk",
        f"CHECK (error_type IS NULL OR error_type IN ({_RUN_ERRORS_WITH_OWNER}))",
    )
    op.execute("UPDATE schedule_runs SET error_type = NULL WHERE error_type = 'owner_inactive'")
    _add_constraint(
        "schedule_runs", "schedule_runs_error_type_chk", f"CHECK (error_type IS NULL OR error_type IN ({_RUN_ERRORS}))"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS conversations_user_listed_idx "
        "ON conversations (user_id, date DESC) WHERE visibility = 'listed'"
    )
    op.execute("DROP INDEX IF EXISTS conversations_user_ws_listed_idx")
    op.execute("DROP INDEX IF EXISTS conversations_team_idx")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS team_id")

    op.execute("DROP TRIGGER IF EXISTS agents_set_updated_at ON agents")
    op.execute(_content_trigger(_BOOKKEEPING))
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_access_payer_person_chk")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS access_payer_id")

    for table in _PROVENANCE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_fill_created_by ON {table}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS created_by")
    op.execute("DROP FUNCTION IF EXISTS fill_created_by()")

    op.execute("ALTER TABLE team_resource_grants DROP CONSTRAINT IF EXISTS team_resource_grants_personal_owner_chk")
    op.execute("ALTER TABLE team_members DROP CONSTRAINT IF EXISTS team_members_person_chk")
    op.execute("ALTER TABLE team_members DROP CONSTRAINT IF EXISTS team_members_role_check")
    # Editor and viewer both become member; keep one row where a person held both from one source.
    op.execute(
        """
        DELETE FROM team_members m WHERE m.role = 'team_viewer' AND EXISTS (
            SELECT 1 FROM team_members e WHERE e.team_id = m.team_id AND e.user_id = m.user_id
               AND e.source = m.source AND e.role = 'team_editor')
        """
    )
    op.execute("UPDATE team_members SET role = 'team_member' WHERE role IN ('team_editor', 'team_viewer')")
    op.execute(
        "ALTER TABLE team_members ADD CONSTRAINT team_members_role_check "
        "CHECK (role IN ('team_admin', 'team_member'))"
    )

    op.execute(_ENSURE_USER_ANY)
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'users' AND column_name = 'kind') THEN
                DELETE FROM users WHERE kind = 'team';
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS users_team_id_uidx")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_team_principal_chk")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_kind_chk")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS team_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS kind")
