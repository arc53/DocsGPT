"""Workspace folders: one tree per owner, the filings backfill and the cleanup triggers survive a round trip."""

import contextlib
import importlib
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

_MIGRATION = "docsgpt.alembic.versions.0064_workspace_folders"
_NEXT = "docsgpt.alembic.versions.0065_workspaces"


@contextlib.contextmanager
def _ops(conn):
    """0064 and 0065 with their ``op`` bound to ``conn``; 0065 is taken off first and put back after."""
    migration = importlib.import_module(_MIGRATION)
    following = importlib.import_module(_NEXT)
    operations = Operations(MigrationContext.configure(conn))
    with patch.object(migration, "op", operations), patch.object(following, "op", operations):
        following.downgrade()
        yield migration
        following.upgrade()


def _table_exists(conn, name: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{name}"}).scalar()


def _columns(conn, table: str) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
        )
    }


def _trigger_def(conn) -> str:
    return conn.execute(
        text(
            "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid = 'agents'::regclass AND tgname = 'agents_set_updated_at'"
        )
    ).scalar()


def _insert_folder(conn, table: str, user: str, name: str, parent: str | None = None, created_at=None) -> str:
    sql = (
        f"INSERT INTO {table} (user_id, name, parent_id, created_at) "
        "VALUES (:u, :n, CAST(:p AS uuid), COALESCE(CAST(:c AS timestamptz), now())) RETURNING id"
    )
    return str(conn.execute(text(sql), {"u": user, "n": name, "p": parent, "c": created_at}).scalar())


def _insert_agent(conn, user: str, name: str) -> str:
    return str(
        conn.execute(
            text("INSERT INTO agents (user_id, name, status) VALUES (:u, :n, 'draft') RETURNING id"),
            {"u": user, "n": name},
        ).scalar()
    )


def _file(conn, user: str, resource_type: str, resource_id: str, folder_id: str) -> None:
    conn.execute(
        text(
            "INSERT INTO folder_items (user_id, resource_type, resource_id, folder_id) "
            "VALUES (:u, :t, CAST(:r AS uuid), CAST(:f AS uuid))"
        ),
        {"u": user, "t": resource_type, "r": resource_id, "f": folder_id},
    )


def _names(conn, table: str = "folders") -> dict:
    return dict(conn.execute(text(f"SELECT id::text, name FROM {table}")).fetchall())


def _indexes(conn) -> set:
    return {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes"))}


def _constraints(conn, table: str) -> set:
    return {
        r[0] for r in conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"),
                                   {"t": table})
    }


def test_head_schema_has_one_folder_tree_and_filings_of_four_kinds(pg_conn):
    assert _table_exists(pg_conn, "folders")
    assert not _table_exists(pg_conn, "agent_folders")
    assert "resource_type" not in _columns(pg_conn, "folders")
    assert "folder_id" not in _columns(pg_conn, "agents")
    assert "knowledge_folder_ids" in _columns(pg_conn, "agents")
    assert "folder_id" not in _trigger_def(pg_conn)
    assert {"folders_sibling_name_uidx", "folder_items_folder_idx", "folder_items_resource_idx"} <= _indexes(pg_conn)
    folder = _insert_folder(pg_conn, "folders", "u", "Everything")
    for n, kind in enumerate(("agent", "source", "tool", "prompt")):
        _file(pg_conn, "u", kind, f"00000000-0000-0000-0000-00000000000{n}", folder)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _file(pg_conn, "u", "workflow", "00000000-0000-0000-0000-000000000001", folder)


def test_sibling_names_are_unique_ignoring_case_across_kinds(pg_conn):
    top = _insert_folder(pg_conn, "folders", "u", "Docs")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _insert_folder(pg_conn, "folders", "u", "docs")
    # Another parent, or another owner, may use the name.
    _insert_folder(pg_conn, "folders", "u", "Docs", parent=top)
    _insert_folder(pg_conn, "folders", "v", "DOCS")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _insert_folder(pg_conn, "folders", "u", "DOCS", parent=top)


def test_a_filing_belongs_to_the_folders_owner(pg_conn):
    folder = _insert_folder(pg_conn, "folders", "u", "Mine")
    agent = _insert_agent(pg_conn, "v", "Theirs")
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _file(pg_conn, "v", "agent", agent, folder)


def test_a_folder_that_changes_owner_takes_its_filings(pg_conn):
    folder = _insert_folder(pg_conn, "folders", "u", "Project")
    agent = _insert_agent(pg_conn, "u", "A")
    _file(pg_conn, "u", "agent", agent, folder)
    pg_conn.execute(text("UPDATE folders SET user_id = 'w' WHERE id = CAST(:f AS uuid)"), {"f": folder})
    rows = pg_conn.execute(text("SELECT user_id, folder_id::text FROM folder_items")).fetchall()
    assert [tuple(r) for r in rows] == [("w", folder)]


def test_round_trip_moves_owner_filings_onto_the_agent_column_and_back(pg_conn):
    with _ops(pg_conn) as migration:
        folder = _insert_folder(pg_conn, "folders", "u", "Customer-facing")
        other_folder = _insert_folder(pg_conn, "folders", "v", "Mine")
        mixed_folder = _insert_folder(pg_conn, "folders", "u", "Carriers")
        agent = _insert_agent(pg_conn, "u", "Helpdesk")
        source = str(
            pg_conn.execute(text("INSERT INTO sources (user_id, name) VALUES ('u', 's') RETURNING id")).scalar()
        )
        _file(pg_conn, "u", "agent", agent, folder)
        _file(pg_conn, "u", "source", source, mixed_folder)
        # Another user's filing of the same agent is theirs alone.
        _file(pg_conn, "v", "agent", agent, other_folder)

        migration.downgrade()
        migration.downgrade()
        assert _table_exists(pg_conn, "agent_folders")
        assert not _table_exists(pg_conn, "folders")
        assert not _table_exists(pg_conn, "folder_items")
        assert "resource_type" not in _columns(pg_conn, "agent_folders")
        assert "knowledge_folder_ids" not in _columns(pg_conn, "agents")
        assert "folder_id" in _trigger_def(pg_conn)
        restored = pg_conn.execute(
            text("SELECT folder_id::text FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}
        ).scalar()
        assert restored == folder
        # A folder that held only sources stays, as an empty agent folder.
        assert {folder, other_folder, mixed_folder} <= set(_names(pg_conn, "agent_folders"))
        indexes = _indexes(pg_conn)
        assert {"agent_folders_pkey", "agent_folders_user_idx", "agents_folder_id_idx"} <= indexes
        assert "folders_sibling_name_uidx" not in indexes
        assert "folders_id_user_uniq" not in _constraints(pg_conn, "agent_folders")

        # Main accepted repeated and blank sibling names.
        dup_a = _insert_folder(pg_conn, "agent_folders", "u", "Docs", created_at="2026-01-01")
        dup_b = _insert_folder(pg_conn, "agent_folders", "u", "docs", created_at="2026-01-02")
        taken = _insert_folder(pg_conn, "agent_folders", "u", "Docs (2)", created_at="2026-01-03")
        blank_a = _insert_folder(pg_conn, "agent_folders", "u", "  ", created_at="2026-01-04")
        blank_b = _insert_folder(pg_conn, "agent_folders", "u", "", created_at="2026-01-05")
        other_parent = _insert_folder(pg_conn, "agent_folders", "u", "Docs", parent=folder)
        # An agent in another user's folder is not filed by the backfill.
        stray = _insert_agent(pg_conn, "u", "Stray")
        pg_conn.execute(
            text("UPDATE agents SET folder_id = CAST(:f AS uuid) WHERE id = CAST(:a AS uuid)"),
            {"f": other_folder, "a": stray},
        )

        migration.upgrade()
        migration.upgrade()
        assert _table_exists(pg_conn, "folders") and not _table_exists(pg_conn, "agent_folders")
        assert "folder_id" not in _columns(pg_conn, "agents")
        assert "resource_type" not in _columns(pg_conn, "folders")
        assert "folder_id" not in _trigger_def(pg_conn)
        filings = pg_conn.execute(
            text("SELECT user_id, resource_id::text, folder_id::text FROM folder_items ORDER BY user_id")
        ).fetchall()
        assert [tuple(r) for r in filings] == [("u", agent, folder)]
        names = _names(pg_conn)
        assert (names[dup_a], names[dup_b], names[taken]) == ("Docs", "docs (3)", "Docs (2)")
        assert (names[blank_a], names[blank_b]) == ("Folder", "Folder (2)")
        assert names[other_parent] == "Docs"
        assert {"folders_pkey", "folders_user_idx", "folders_parent_idx", "folders_sibling_name_uidx"} <= _indexes(
            pg_conn
        )
        assert {"folders_id_user_uniq"} <= _constraints(pg_conn, "folders")
        assert {"folder_items_folder_fk", "folder_items_resource_type_chk"} <= _constraints(pg_conn, "folder_items")
        triggers = {
            r[0] for r in pg_conn.execute(text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'folders'::regclass"))
        }
        assert {"folders_set_updated_at", "folders_ensure_user", "folders_cleanup_agent_knowledge_refs"} <= triggers


def test_upgrade_converts_a_database_stamped_at_the_earlier_draft(pg_conn):
    """The draft gave folders a kind; re-running the upgrade over it keeps folders and filings."""
    with _ops(pg_conn) as migration:
        # Put the draft's shape back: a kind on folders, two kinds of filing, a plain folder FK.
        pg_conn.execute(text("DROP INDEX folders_sibling_name_uidx"))
        pg_conn.execute(text("ALTER TABLE folder_items DROP CONSTRAINT folder_items_folder_fk"))
        pg_conn.execute(text("ALTER TABLE folders DROP CONSTRAINT folders_id_user_uniq"))
        pg_conn.execute(text("ALTER TABLE folders ADD COLUMN resource_type TEXT NOT NULL DEFAULT 'agent'"))
        pg_conn.execute(
            text(
                "ALTER TABLE folders ADD CONSTRAINT folders_resource_type_chk "
                "CHECK (resource_type IN ('agent', 'source'))"
            )
        )
        pg_conn.execute(text("CREATE INDEX folders_user_type_idx ON folders (user_id, resource_type)"))
        pg_conn.execute(text("ALTER TABLE folder_items DROP CONSTRAINT folder_items_resource_type_chk"))
        pg_conn.execute(
            text(
                "ALTER TABLE folder_items ADD CONSTRAINT folder_items_resource_type_chk "
                "CHECK (resource_type IN ('agent', 'source'))"
            )
        )
        pg_conn.execute(
            text(
                "ALTER TABLE folder_items ADD CONSTRAINT folder_items_folder_id_fkey "
                "FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE"
            )
        )
        agent_folder = _insert_folder(pg_conn, "folders", "u", "Agents", created_at="2026-01-01")
        source_folder = str(
            pg_conn.execute(
                text("INSERT INTO folders (user_id, name, resource_type) VALUES ('u', 'agents', 'source') RETURNING id")
            ).scalar()
        )
        source = str(
            pg_conn.execute(text("INSERT INTO sources (user_id, name) VALUES ('u', 's') RETURNING id")).scalar()
        )
        _file(pg_conn, "u", "source", source, source_folder)

        migration.upgrade()

        assert "resource_type" not in _columns(pg_conn, "folders")
        assert "folders_user_type_idx" not in _indexes(pg_conn)
        assert {"folder_items_folder_fk"} <= _constraints(pg_conn, "folder_items")
        assert "folder_items_folder_id_fkey" not in _constraints(pg_conn, "folder_items")
        names = _names(pg_conn)
        assert (names[agent_folder], names[source_folder]) == ("Agents", "agents (2)")
        filed = pg_conn.execute(text("SELECT resource_id::text, folder_id::text FROM folder_items")).fetchall()
        assert [tuple(r) for r in filed] == [(source, source_folder)]
        _file(pg_conn, "u", "tool", "00000000-0000-0000-0000-000000000009", agent_folder)


def test_deleting_an_item_of_any_kind_drops_its_filings(pg_conn):
    folder = _insert_folder(pg_conn, "folders", "u", "Everything")
    agent = _insert_agent(pg_conn, "u", "A")
    source = str(
        pg_conn.execute(text("INSERT INTO sources (user_id, name) VALUES ('u', 's') RETURNING id")).scalar()
    )
    tool = str(
        pg_conn.execute(text("INSERT INTO user_tools (user_id, name) VALUES ('u', 'api_tool') RETURNING id")).scalar()
    )
    prompt = str(
        pg_conn.execute(
            text("INSERT INTO prompts (user_id, name, content) VALUES ('u', 'p', 'c') RETURNING id")
        ).scalar()
    )
    for kind, item in (("agent", agent), ("source", source), ("tool", tool), ("prompt", prompt)):
        _file(pg_conn, "u", kind, item, folder)
    for table, item in (("agents", agent), ("sources", source), ("user_tools", tool), ("prompts", prompt)):
        pg_conn.execute(text(f"DELETE FROM {table} WHERE id = CAST(:i AS uuid)"), {"i": item})
        remaining = pg_conn.execute(
            text("SELECT count(*) FROM folder_items WHERE resource_id = CAST(:i AS uuid)"), {"i": item}
        ).scalar()
        assert remaining == 0, table


def test_deleting_a_folder_drops_it_from_agents_knowledge_folders(pg_conn):
    kept = _insert_folder(pg_conn, "folders", "u", "Kept")
    gone = _insert_folder(pg_conn, "folders", "u", "Gone")
    agent = _insert_agent(pg_conn, "u", "A")
    pg_conn.execute(
        text(
            "UPDATE agents SET knowledge_folder_ids = ARRAY[CAST(:k AS uuid), CAST(:g AS uuid)] "
            "WHERE id = CAST(:a AS uuid)"
        ),
        {"k": kept, "g": gone, "a": agent},
    )
    pg_conn.execute(text("DELETE FROM folders WHERE id = CAST(:g AS uuid)"), {"g": gone})
    refs = pg_conn.execute(
        text("SELECT knowledge_folder_ids::text[] FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}
    ).scalar()
    assert refs == [kept]


def test_filing_does_not_move_the_agents_updated_at(pg_conn):
    folder = _insert_folder(pg_conn, "folders", "u", "F")
    agent = _insert_agent(pg_conn, "u", "A")
    # ``now()`` is fixed inside the test's transaction: only an older stamp shows a bump.
    from tests.storage.db.repositories.test_agents import _age

    before = _age(pg_conn, agent)
    _file(pg_conn, "u", "agent", agent, folder)
    after = pg_conn.execute(text("SELECT updated_at FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}).scalar()
    assert before == after
