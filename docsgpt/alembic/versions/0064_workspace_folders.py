"""0064 workspace folders — one folder tree per owner for agents, knowledge, tools and prompts.

* ``agent_folders`` becomes ``folders`` (indexes, constraints and triggers
  renamed with it). A folder has no kind: it can hold items of all four kinds.
  Sibling names are unique ignoring case per owner and parent, across kinds
  (``folders_sibling_name_uidx``); names repeated by main's agent folders get
  " (2)", " (3)" ... and blank names become "Folder" first.
* ``folder_items``: filing (``agent``, ``source``, ``tool`` or ``prompt``), one
  filing per item per user (primary key ``(user_id, resource_type,
  resource_id)``). The composite FK ``(folder_id, user_id) → folders (id,
  user_id)`` keeps every filing in a folder of its own user, and follows the
  folder when its owner changes (``ON UPDATE CASCADE``).
* Backfill: every ``agents.folder_id`` whose folder belongs to the agent's
  owner becomes the owner's filing; then ``agents.folder_id`` (and its index)
  is dropped, and ``agents_set_updated_at`` (0060) stops listing it as a
  bookkeeping column.
* ``AFTER DELETE`` triggers on ``agents``, ``sources``, ``user_tools`` and
  ``prompts`` remove their filings.
* ``agents.knowledge_folder_ids``: folders an agent reads live (a GIN index
  for the ``used_by`` lookups); deleting a folder removes its id from every
  agent.

Idempotent both ways, and the upgrade also converts a database stamped at an
earlier draft of this revision (folders with a ``resource_type`` column) in
place. Downgrade puts each owner's filing of their own agent back on
``agents.folder_id`` (other users' filings and every other kind's filings are
lost), drops the sibling-name rule and renames the table back; folders that
held only other kinds stay as empty agent folders.

Revision ID: 0064_workspace_folders
Revises: 0063_run_cannot_complete
"""

from alembic import op

revision = "0064_workspace_folders"
down_revision = "0063_run_cannot_complete"
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


#: The nil UUID stands in for "no parent" in the sibling-name index.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"

#: ``(table, resource_type)`` of every kind a folder can hold.
_FILED_TABLES = (("agents", "agent"), ("sources", "source"), ("user_tools", "tool"), ("prompts", "prompt"))


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
    """Rename agent folders to one folder tree, add filings, move ``agents.folder_id`` onto them, add live refs."""
    _rename_table("agent_folders", "folders")
    _rename_names("folders", _TRIGGER_RENAMES)

    # One tree per owner: a folder has no kind (an earlier draft of this revision gave it one).
    op.execute("ALTER TABLE folders DROP CONSTRAINT IF EXISTS folders_resource_type_chk")
    op.execute("DROP INDEX IF EXISTS folders_user_type_idx")
    op.execute("ALTER TABLE folders DROP COLUMN IF EXISTS resource_type")
    # Main accepted blank and repeated sibling names; give each clash a free " (n)" before the unique index.
    op.execute("UPDATE folders SET name = 'Folder' WHERE btrim(name) = ''")
    op.execute(
        """
        DO $$
        DECLARE
            r record;
            k int;
            candidate text;
        BEGIN
            FOR r IN
                SELECT d.id, d.user_id, d.parent_id, d.name FROM (
                    SELECT id, user_id, parent_id, name, created_at,
                           row_number() OVER (PARTITION BY user_id, parent_id, lower(name)
                                              ORDER BY created_at, id) AS n
                    FROM folders) d
                WHERE d.n > 1
                ORDER BY d.user_id, d.parent_id, lower(d.name), d.created_at, d.id
            LOOP
                k := 2;
                LOOP
                    candidate := left(r.name, 74) || ' (' || k || ')';
                    EXIT WHEN NOT EXISTS (
                        SELECT 1 FROM folders f
                        WHERE f.user_id = r.user_id AND f.parent_id IS NOT DISTINCT FROM r.parent_id
                          AND lower(f.name) = lower(candidate));
                    k := k + 1;
                END LOOP;
                UPDATE folders SET name = candidate WHERE id = r.id;
            END LOOP;
        END $$;
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS folders_sibling_name_uidx "
        f"ON folders (user_id, COALESCE(parent_id, '{_NIL_UUID}'::uuid), lower(name))"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'folders_id_user_uniq') THEN
                ALTER TABLE folders ADD CONSTRAINT folders_id_user_uniq UNIQUE (id, user_id);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS folder_items (
            user_id         TEXT NOT NULL,
            resource_type   TEXT NOT NULL,
            resource_id     UUID NOT NULL,
            folder_id       UUID NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, resource_type, resource_id)
        )
        """
    )
    # Constraints apart from the table so a re-run over the earlier draft's table converts it.
    op.execute("ALTER TABLE folder_items DROP CONSTRAINT IF EXISTS folder_items_resource_type_chk")
    op.execute(
        "ALTER TABLE folder_items ADD CONSTRAINT folder_items_resource_type_chk "
        "CHECK (resource_type IN ('agent', 'source', 'tool', 'prompt'))"
    )
    op.execute("ALTER TABLE folder_items DROP CONSTRAINT IF EXISTS folder_items_folder_id_fkey")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'folder_items_folder_fk') THEN
                DELETE FROM folder_items fi WHERE NOT EXISTS (
                    SELECT 1 FROM folders f WHERE f.id = fi.folder_id AND f.user_id = fi.user_id);
                ALTER TABLE folder_items ADD CONSTRAINT folder_items_folder_fk
                    FOREIGN KEY (folder_id, user_id) REFERENCES folders (id, user_id)
                    ON DELETE CASCADE ON UPDATE CASCADE;
            END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS folder_items_folder_idx ON folder_items (folder_id)")
    op.execute("CREATE INDEX IF NOT EXISTS folder_items_resource_idx ON folder_items (resource_type, resource_id)")
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
                JOIN folders f ON f.id = a.folder_id AND f.user_id = a.user_id
                ON CONFLICT (user_id, resource_type, resource_id) DO NOTHING;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS agents_set_updated_at ON agents")
    op.execute(_content_trigger(_BOOKKEEPING))
    op.execute("DROP INDEX IF EXISTS agents_folder_id_idx")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS folder_id")

    # A deleted agent, source, tool or prompt leaves no filing behind.
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
    for table, resource_type in _FILED_TABLES:
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
    """Put owners' agent filings back on ``agents.folder_id``, drop filings and the name rule, rename back."""
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

    for table, _resource_type in _FILED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_cleanup_folder_items ON {table}")
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

    # An earlier draft of this revision kept a kind on folders; its source folders go with it.
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
    op.execute("DROP INDEX IF EXISTS folders_sibling_name_uidx")
    op.execute(
        f"""
        DO $$ BEGIN
            IF {folders_exist} THEN
                ALTER TABLE folders DROP CONSTRAINT IF EXISTS folders_resource_type_chk;
                ALTER TABLE folders DROP COLUMN IF EXISTS resource_type;
                ALTER TABLE folders DROP CONSTRAINT IF EXISTS folders_id_user_uniq;
            END IF;
        END $$;
        """
    )
    _rename_table("folders", "agent_folders")
    _rename_names("agent_folders", _TRIGGER_RENAMES, reverse=True)
