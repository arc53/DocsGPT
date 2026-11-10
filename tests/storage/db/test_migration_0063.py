"""Workspace folders: the rename, the filings backfill and the cleanup triggers survive a round trip."""

import importlib
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

_MIGRATION = "docsgpt.alembic.versions.0063_workspace_folders"


def _ops(conn):
    migration = importlib.import_module(_MIGRATION)
    return migration, patch.object(migration, "op", Operations(MigrationContext.configure(conn)))


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


def _insert_folder(conn, table: str, user: str, name: str, resource_type: str | None = None) -> str:
    if resource_type is None:
        sql = f"INSERT INTO {table} (user_id, name) VALUES (:u, :n) RETURNING id"
        return str(conn.execute(text(sql), {"u": user, "n": name}).scalar())
    sql = f"INSERT INTO {table} (user_id, name, resource_type) VALUES (:u, :n, :t) RETURNING id"
    return str(conn.execute(text(sql), {"u": user, "n": name, "t": resource_type}).scalar())


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


def test_head_schema_has_folders_and_filings(pg_conn):
    assert _table_exists(pg_conn, "folders")
    assert not _table_exists(pg_conn, "agent_folders")
    assert "resource_type" in _columns(pg_conn, "folders")
    assert "folder_id" not in _columns(pg_conn, "agents")
    assert "knowledge_folder_ids" in _columns(pg_conn, "agents")
    assert "folder_id" not in _trigger_def(pg_conn)
    with pytest.raises(IntegrityError), pg_conn.begin_nested():
        _insert_folder(pg_conn, "folders", "u", "bad", "tool")


def test_round_trip_moves_owner_filings_onto_the_agent_column_and_back(pg_conn):
    migration, patched = _ops(pg_conn)
    with patched:
        folder = _insert_folder(pg_conn, "folders", "u", "Customer-facing", "agent")
        other_folder = _insert_folder(pg_conn, "folders", "v", "Mine", "agent")
        source_folder = _insert_folder(pg_conn, "folders", "u", "Carriers", "source")
        agent = _insert_agent(pg_conn, "u", "Helpdesk")
        _file(pg_conn, "u", "agent", agent, folder)
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
        ids = {r[0] for r in pg_conn.execute(text("SELECT id::text FROM agent_folders"))}
        assert {folder, other_folder} <= ids and source_folder not in ids
        indexes = {r[0] for r in pg_conn.execute(text("SELECT indexname FROM pg_indexes"))}
        assert {"agent_folders_pkey", "agent_folders_user_idx", "agents_folder_id_idx"} <= indexes

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
        assert "folder_id" not in _trigger_def(pg_conn)
        filings = pg_conn.execute(
            text("SELECT user_id, resource_id::text, folder_id::text FROM folder_items ORDER BY user_id")
        ).fetchall()
        assert [tuple(r) for r in filings] == [("u", agent, folder)]
        types = dict(pg_conn.execute(text("SELECT id::text, resource_type FROM folders")).fetchall())
        assert types[folder] == "agent"
        indexes = {r[0] for r in pg_conn.execute(text("SELECT indexname FROM pg_indexes"))}
        assert {"folders_pkey", "folders_user_idx", "folders_parent_idx", "folders_user_type_idx"} <= indexes
        triggers = {
            r[0] for r in pg_conn.execute(text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'folders'::regclass"))
        }
        assert {"folders_set_updated_at", "folders_ensure_user", "folders_cleanup_agent_knowledge_refs"} <= triggers


def test_deleting_an_agent_or_source_drops_its_filings(pg_conn):
    folder = _insert_folder(pg_conn, "folders", "u", "Agents", "agent")
    source_folder = _insert_folder(pg_conn, "folders", "u", "Knowledge", "source")
    agent = _insert_agent(pg_conn, "u", "A")
    source = str(
        pg_conn.execute(text("INSERT INTO sources (user_id, name) VALUES ('u', 's') RETURNING id")).scalar()
    )
    _file(pg_conn, "u", "agent", agent, folder)
    _file(pg_conn, "u", "source", source, source_folder)
    pg_conn.execute(text("DELETE FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent})
    pg_conn.execute(text("DELETE FROM sources WHERE id = CAST(:s AS uuid)"), {"s": source})
    assert pg_conn.execute(text("SELECT count(*) FROM folder_items")).scalar() == 0


def test_deleting_a_folder_drops_it_from_agents_knowledge_folders(pg_conn):
    kept = _insert_folder(pg_conn, "folders", "u", "Kept", "source")
    gone = _insert_folder(pg_conn, "folders", "u", "Gone", "source")
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
    folder = _insert_folder(pg_conn, "folders", "u", "F", "agent")
    agent = _insert_agent(pg_conn, "u", "A")
    before = pg_conn.execute(text("SELECT updated_at FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}).scalar()
    _file(pg_conn, "u", "agent", agent, folder)
    after = pg_conn.execute(text("SELECT updated_at FROM agents WHERE id = CAST(:a AS uuid)"), {"a": agent}).scalar()
    assert before == after
