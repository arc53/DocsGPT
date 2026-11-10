"""0063 workspace folders — one folder system for agents and knowledge, filed per user.

* ``agent_folders`` becomes ``folders`` (indexes, constraints and triggers
  renamed with it) and gains ``resource_type`` (``agent`` or ``source``,
  existing rows are agent folders) with an index on ``(user_id, resource_type)``.
* ``folder_items``: personal filing. Each user files any item they can see into
  one of their own folders of the same type; one filing per item per user
  (primary key ``(user_id, resource_type, resource_id)``). The repository keeps
  the folder's owner and type equal to the row's.
* Backfill: every ``agents.folder_id`` whose folder belongs to the agent's
  owner becomes the owner's filing; then ``agents.folder_id`` (and its index)
  is dropped, and ``agents_set_updated_at`` (0060) stops listing it as a
  bookkeeping column.
* ``AFTER DELETE`` triggers on ``agents`` and ``sources`` remove their filings.
* ``agents.knowledge_folder_ids``: source folders an agent reads live (a GIN
  index for the ``used_by`` lookups); deleting a folder removes its id from
  every agent.

Idempotent both ways. Downgrade puts each owner's filing of their own agent
back on ``agents.folder_id`` (other users' filings of it are lost), deletes
source folders and the filings, and renames the table back.

Revision ID: 0063_workspace_folders
Revises: 0062_ingest_resume
"""

from alembic import op

revision = "0063_workspace_folders"
down_revision = "0062_ingest_resume"
branch_labels = None
depends_on = None


#: ``(old, new)`` index names of the renamed table.
_INDEX_RENAMES = (
    ("agent_folders_pkey", "folders_pkey"),
    ("agent_folders_user_idx", "folders_user_idx"),
    ("agent_folders_parent_idx", "folders_parent_idx"),
    ("agent_folders_legacy_mongo_id_uidx", "folders_legacy_mongo_id_uidx"),
)

#: ``(old, new)`` constraint names (the primary key's index is renamed with it).
_CONSTRAINT_RENAMES = (
    ("agent_folders_parent_id_fkey", "folders_parent_id_fkey"),
    ("agent_folders_user_id_fk", "folders_user_id_fk"),
)

#: ``(old, new)`` trigger names.
_TRIGGER_RENAMES = (
    ("agent_folders_set_updated_at", "folders_set_updated_at"),
    ("agent_folders_ensure_user", "folders_ensure_user"),
)

#: Bookkeeping agent columns the ``agents_set_updated_at`` trigger skips (0060), with and without ``folder_id``.
_BOOKKEEPING_WITH_FOLDER = (
    "ARRAY['updated_at', 'last_used_at', 'key', 'incoming_webhook_token', "
    "'shared', 'shared_token', 'shared_metadata', 'slug', 'folder_id']"
)
_BOOKKEEPING = (
    "ARRAY['updated_at', 'last_used_at', 'key', 'incoming_webhook_token', "
    "'shared', 'shared_token', 'shared_metadata', 'slug']"
)


def _content_trigger(bookkeeping: str) -> str:
    """The ``agents_set_updated_at`` trigger that ignores ``bookkeeping`` columns."""
    return (
        "CREATE TRIGGER agents_set_updated_at BEFORE UPDATE ON agents FOR EACH ROW "
        f"WHEN ((to_jsonb(OLD) - {bookkeeping}) IS DISTINCT FROM (to_jsonb(NEW) - {bookkeeping})) "
        "EXECUTE FUNCTION set_updated_at()"
    )


def _rename_table(old: str, new: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF to_regclass('public.{old}') IS NOT NULL AND to_regclass('public.{new}') IS NULL THEN
                ALTER TABLE {old} RENAME TO {new};
            END IF;
        END $$;
        """
    )


def _rename_names(table: str, pairs: tuple, *, reverse: bool = False) -> None:
    """Rename the table's indexes, constraints and triggers (``reverse`` swaps each pair)."""
    for old, new in _INDEX_RENAMES:
        if reverse:
            old, new = new, old
        if old.endswith("_pkey"):
            continue  # renamed with its constraint below
        op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")
    for old, new in (("agent_folders_pkey", "folders_pkey"), *_CONSTRAINT_RENAMES):
        if reverse:
            old, new = new, old
        op.execute(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{old}'
                           AND conrelid = '{table}'::regclass) THEN
                    ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new};
                END IF;
            END $$;
            """
        )
    for old, new in pairs:
        if reverse:
            old, new = new, old
        op.execute(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = '{old}' AND tgrelid = '{table}'::regclass) THEN
                    ALTER TRIGGER {old} ON {table} RENAME TO {new};
                END IF;
            END $$;
            """
        )


def upgrade() -> None:
    """Rename agent folders to folders, add filings, move ``agents.folder_id`` onto them, add live folder refs."""
    _rename_table("agent_folders", "folders")
    _rename_names("folders", _TRIGGER_RENAMES)
    op.execute("ALTER TABLE folders ADD COLUMN IF NOT EXISTS resource_type TEXT NOT NULL DEFAULT 'agent'")
    op.execute("ALTER TABLE folders DROP CONSTRAINT IF EXISTS folders_resource_type_chk")
    op.execute(
        "ALTER TABLE folders ADD CONSTRAINT folders_resource_type_chk "
        "CHECK (resource_type IN ('agent', 'source'))"
    )
    op.execute("CREATE INDEX IF NOT EXISTS folders_user_type_idx ON folders (user_id, resource_type)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS folder_items (
            user_id         TEXT NOT NULL,
            resource_type   TEXT NOT NULL CONSTRAINT folder_items_resource_type_chk
                                CHECK (resource_type IN ('agent', 'source')),
            resource_id     UUID NOT NULL,
            folder_id       UUID NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, resource_type, resource_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS folder_items_folder_idx ON folder_items (folder_id)")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'folder_items_user_id_fk') THEN
                ALTER TABLE folder_items ADD CONSTRAINT folder_items_user_id_fk
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS folder_items_ensure_user ON folder_items")
    op.execute(
        "CREATE TRIGGER folder_items_ensure_user BEFORE INSERT OR UPDATE OF user_id ON folder_items "
        "FOR EACH ROW EXECUTE FUNCTION ensure_user_exists()"
    )

    # The owner's folder of each agent becomes their filing, then the column goes.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'agents' AND column_name = 'folder_id') THEN
                INSERT INTO folder_items (user_id, resource_type, resource_id, folder_id)
                SELECT a.user_id, 'agent', a.id, a.folder_id
                FROM agents a
                JOIN folders f ON f.id = a.folder_id AND f.user_id = a.user_id AND f.resource_type = 'agent'
                ON CONFLICT (user_id, resource_type, resource_id) DO NOTHING;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS agents_set_updated_at ON agents")
    op.execute(_content_trigger(_BOOKKEEPING))
    op.execute("DROP INDEX IF EXISTS agents_folder_id_idx")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS folder_id")

    # A deleted agent or source leaves no filing behind.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cleanup_folder_items() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM folder_items WHERE resource_type = TG_ARGV[0] AND resource_id = OLD.id;
            RETURN OLD;
        END;
        $$;
        """
    )
    for table, resource_type in (("agents", "agent"), ("sources", "source")):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_cleanup_folder_items ON {table}")
        op.execute(
            f"CREATE TRIGGER {table}_cleanup_folder_items AFTER DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION cleanup_folder_items('{resource_type}')"
        )

    # Live knowledge folders on an agent; a deleted folder drops out of every agent.
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS knowledge_folder_ids UUID[] NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS agents_knowledge_folder_ids_gin_idx ON agents USING gin (knowledge_folder_ids)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cleanup_agent_knowledge_folder_refs() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE agents
            SET knowledge_folder_ids = array_remove(knowledge_folder_ids, OLD.id)
            WHERE OLD.id = ANY(knowledge_folder_ids);
            RETURN OLD;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS folders_cleanup_agent_knowledge_refs ON folders")
    op.execute(
        "CREATE TRIGGER folders_cleanup_agent_knowledge_refs AFTER DELETE ON folders "
        "FOR EACH ROW EXECUTE FUNCTION cleanup_agent_knowledge_folder_refs()"
    )


def downgrade() -> None:
    """Put owners' agent filings back on ``agents.folder_id``, drop filings and source folders, rename back."""
    folders_exist = "to_regclass('public.folders') IS NOT NULL"
    op.execute(
        f"""
        DO $$ BEGIN
            IF {folders_exist} THEN
                DROP TRIGGER IF EXISTS folders_cleanup_agent_knowledge_refs ON folders;
            END IF;
        END $$;
        """
    )
    op.execute("DROP FUNCTION IF EXISTS cleanup_agent_knowledge_folder_refs()")
    op.execute("DROP INDEX IF EXISTS agents_knowledge_folder_ids_gin_idx")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS knowledge_folder_ids")

    op.execute("DROP TRIGGER IF EXISTS agents_cleanup_folder_items ON agents")
    op.execute("DROP TRIGGER IF EXISTS sources_cleanup_folder_items ON sources")
    op.execute("DROP FUNCTION IF EXISTS cleanup_folder_items()")

    # 0060's trigger, folder_id among the bookkeeping columns, before the column is written.
    op.execute("DROP TRIGGER IF EXISTS agents_set_updated_at ON agents")
    op.execute(_content_trigger(_BOOKKEEPING_WITH_FOLDER))
    op.execute(
        f"""
        DO $$ BEGIN
            IF {folders_exist} THEN
                ALTER TABLE agents ADD COLUMN IF NOT EXISTS folder_id UUID
                    REFERENCES folders(id) ON DELETE SET NULL;
            ELSE
                ALTER TABLE agents ADD COLUMN IF NOT EXISTS folder_id UUID
                    REFERENCES agent_folders(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS agents_folder_id_idx ON agents (folder_id)")
    op.execute(
        """
        DO $$ BEGIN
            IF to_regclass('public.folder_items') IS NOT NULL THEN
                UPDATE agents a SET folder_id = fi.folder_id
                FROM folder_items fi
                WHERE fi.resource_type = 'agent' AND fi.resource_id = a.id AND fi.user_id = a.user_id;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS folder_items")

    op.execute(
        f"""
        DO $$ BEGIN
            IF {folders_exist} AND EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'folders' AND column_name = 'resource_type') THEN
                DELETE FROM folders WHERE resource_type = 'source';
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS folders_user_type_idx")
    op.execute(
        f"""
        DO $$ BEGIN
            IF {folders_exist} THEN
                ALTER TABLE folders DROP CONSTRAINT IF EXISTS folders_resource_type_chk;
                ALTER TABLE folders DROP COLUMN IF EXISTS resource_type;
            END IF;
        END $$;
        """
    )
    _rename_table("folders", "agent_folders")
    _rename_names("agent_folders", _TRIGGER_RENAMES, reverse=True)
