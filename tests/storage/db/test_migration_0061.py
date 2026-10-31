"""Agent starters survive an idempotent migration round trip and count as content."""

import importlib
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository

_MIGRATION = "docsgpt.alembic.versions.0061_agent_starters"


def _columns(conn) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'agents'")
        )
    }


def test_round_trip_adds_and_drops_the_column(pg_conn):
    migration = importlib.import_module(_MIGRATION)
    repo = AgentsRepository(pg_conn)
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.downgrade()
        assert "starters" not in _columns(pg_conn)
        # An agent made before the column exists gets ``[]``.
        pg_conn.execute(text("INSERT INTO agents (user_id, name, status) VALUES ('u', 'old', 'draft')"))
        migration.upgrade()
        migration.upgrade()
        assert pg_conn.execute(text("SELECT starters FROM agents WHERE name = 'old'")).scalar() == []
        row = repo.create("u", "a", "draft", starters=["Hi?"])
        assert repo.get(str(row["id"]), "u")["starters"] == ["Hi?"]
        migration.downgrade()
        migration.downgrade()
        assert "starters" not in _columns(pg_conn)
        assert pg_conn.execute(text("SELECT count(*) FROM agents")).scalar() == 2
        migration.upgrade()
        assert "starters" in _columns(pg_conn)


def _updated_at(conn, agent_id):
    return conn.execute(
        text("SELECT updated_at FROM agents WHERE id = CAST(:id AS uuid)"), {"id": agent_id}
    ).scalar()


def test_a_starters_change_moves_updated_at_and_bookkeeping_does_not(pg_conn):
    """0060's trigger skips only the bookkeeping columns, so ``starters`` is content without a trigger change."""
    agent_id = str(AgentsRepository(pg_conn).create("u", "a", "draft")["id"])
    pg_conn.execute(
        text("UPDATE agents SET updated_at = '2020-01-01T00:00:00Z' WHERE id = CAST(:id AS uuid)"),
        {"id": agent_id},
    )
    stamp = _updated_at(pg_conn, agent_id)
    pg_conn.execute(text("UPDATE agents SET last_used_at = now() WHERE id = CAST(:id AS uuid)"), {"id": agent_id})
    assert _updated_at(pg_conn, agent_id) == stamp
    pg_conn.execute(
        text("UPDATE agents SET starters = CAST('[\"Hi?\"]' AS jsonb) WHERE id = CAST(:id AS uuid)"),
        {"id": agent_id},
    )
    assert _updated_at(pg_conn, agent_id) > stamp
